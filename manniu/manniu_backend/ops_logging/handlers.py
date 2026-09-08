import atexit
import hashlib
import logging
import os
import queue
import socket
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.db import close_old_connections

from ops_logging.runtime import current_correlation_id, current_request_id, current_run_id
from ops_logging.sanitizer import sanitize_text, sanitize_value


@dataclass
class _FlushRequest:
    completed: threading.Event


class DatabaseLogHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=getattr(logging, settings.OPS_DB_LOG_LEVEL, logging.INFO))
        self._queue = queue.Queue(maxsize=settings.OPS_DB_LOG_QUEUE_SIZE)
        self._writer = threading.Thread(
            target=self._write_loop,
            name='ops-db-log-writer',
            daemon=True,
        )
        self._writer.start()
        self._last_fallback_at = 0.0
        self.enqueued_total = 0
        self.persisted_total = 0
        self.dropped_low_level_total = 0
        self.fallback_stderr_total = 0
        self.batch_write_failures_total = 0

    def emit(self, record):
        try:
            payload = self._build_payload(record)
            self._queue.put_nowait(payload)
            self.enqueued_total += 1
        except queue.Full:
            if record.levelno < logging.WARNING:
                self.dropped_low_level_total += 1
                return
            try:
                self._queue.put(payload, timeout=0.05)
                self.enqueued_total += 1
            except queue.Full:
                self._fallback(f'log queue full: {record.getMessage()}')
        except Exception as exc:
            self._fallback(f'log serialization failed: {exc}')

    def flush_with_timeout(self, timeout=2.0):
        completed = threading.Event()
        try:
            self._queue.put(_FlushRequest(completed), timeout=min(timeout, 0.1))
        except queue.Full:
            return False
        return completed.wait(timeout)

    def health_snapshot(self):
        return {
            'enqueued_total': self.enqueued_total,
            'persisted_total': self.persisted_total,
            'dropped_low_level_total': self.dropped_low_level_total,
            'fallback_stderr_total': self.fallback_stderr_total,
            'batch_write_failures_total': self.batch_write_failures_total,
            'queue_depth': self._queue.qsize(),
            'writer_alive': self._writer.is_alive(),
        }

    def _build_payload(self, record):
        exception_type = None
        exception_message = None
        exception_stack = None
        if record.exc_info:
            exception = record.exc_info[1]
            exception_type = type(exception).__name__ if exception else None
            exception_message = sanitize_text(exception, settings.OPS_DB_LOG_MESSAGE_MAX)
            exception_stack = sanitize_text(
                ''.join(traceback.format_exception(*record.exc_info)),
                settings.OPS_DB_LOG_STACK_MAX,
            )
        event_code = sanitize_text(getattr(record, 'event_code', ''), 96) or None
        fingerprint = None
        if exception_type:
            fingerprint_source = f'{event_code}|{exception_type}|{record.module}|{record.funcName}'
            fingerprint = hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()
        return {
            'event_id': getattr(record, 'event_id', None) or uuid.uuid4(),
            'run_id': getattr(record, 'run_id', None) or current_run_id.get(),
            'occurred_at': datetime.fromtimestamp(record.created, tz=datetime_timezone.utc),
            'level_no': record.levelno,
            'level_name': record.levelname[:10],
            'logger_name': record.name[:160],
            'event_code': event_code,
            'message': sanitize_text(record.getMessage(), settings.OPS_DB_LOG_MESSAGE_MAX),
            'context': sanitize_value(getattr(record, 'context', {})),
            'exception_type': exception_type,
            'exception_message': exception_message,
            'exception_stack': exception_stack,
            'fingerprint': fingerprint,
            'source_module': record.module[:160] if record.module else None,
            'source_function': record.funcName[:160] if record.funcName else None,
            'source_line': record.lineno,
            'correlation_id': (
                getattr(record, 'correlation_id', None) or current_correlation_id.get()
            ),
            'request_id': getattr(record, 'request_id', None) or current_request_id.get(),
            'host_name': socket.gethostname()[:128],
            'process_id': os.getpid(),
        }

    def _write_loop(self):
        while True:
            try:
                first_item = self._queue.get(timeout=settings.OPS_DB_LOG_FLUSH_SECONDS)
            except queue.Empty:
                continue
            batch = []
            flush_requests = []
            self._collect_item(first_item, batch, flush_requests)
            deadline = time.monotonic() + settings.OPS_DB_LOG_FLUSH_SECONDS
            while len(batch) < settings.OPS_DB_LOG_BATCH_SIZE:
                if flush_requests:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                self._collect_item(item, batch, flush_requests)
            if batch:
                self._write_batch(batch)
            for request in flush_requests:
                request.completed.set()

    @staticmethod
    def _collect_item(item, batch, flush_requests):
        if isinstance(item, _FlushRequest):
            flush_requests.append(item)
        else:
            batch.append(item)

    def _write_batch(self, batch):
        try:
            close_old_connections()
            from ops_logging.models import LogEntry

            LogEntry.objects.bulk_create(
                [LogEntry(**payload) for payload in batch],
                ignore_conflicts=True,
                batch_size=settings.OPS_DB_LOG_BATCH_SIZE,
            )
            self.persisted_total += len(batch)
        except Exception as exc:
            self.batch_write_failures_total += 1
            self._fallback(f'database log batch failed; dropped={len(batch)} error={exc}')
        finally:
            close_old_connections()

    def _fallback(self, message):
        self.fallback_stderr_total += 1
        now = time.monotonic()
        if now - self._last_fallback_at >= 30:
            self._last_fallback_at = now
            sys.stderr.write(f'[ops_logging] {sanitize_text(message, 1000)}\n')


_handler = None
_configure_lock = threading.Lock()


def configure_database_logging():
    global _handler
    if not settings.OPS_DB_LOG_ENABLED or _handler is not None:
        return
    with _configure_lock:
        if _handler is not None:
            return
        _validate_settings()
        _handler = DatabaseLogHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(_handler)
        if root_logger.level > _handler.level:
            root_logger.setLevel(_handler.level)
        atexit.register(flush_database_logs)


def flush_database_logs(timeout=2.0):
    if _handler is None:
        return True
    return _handler.flush_with_timeout(timeout)


def get_database_log_health():
    if _handler is None:
        return {'enabled': False}
    return {'enabled': True, **_handler.health_snapshot()}


def _validate_settings():
    if settings.OPS_DB_LOG_LEVEL not in logging.getLevelNamesMapping():
        raise ValueError(f'Invalid OPS_DB_LOG_LEVEL: {settings.OPS_DB_LOG_LEVEL}')
    positive_values = {
        'OPS_DB_LOG_QUEUE_SIZE': settings.OPS_DB_LOG_QUEUE_SIZE,
        'OPS_DB_LOG_BATCH_SIZE': settings.OPS_DB_LOG_BATCH_SIZE,
        'OPS_DB_LOG_FLUSH_SECONDS': settings.OPS_DB_LOG_FLUSH_SECONDS,
        'OPS_DB_LOG_MESSAGE_MAX': settings.OPS_DB_LOG_MESSAGE_MAX,
        'OPS_DB_LOG_STACK_MAX': settings.OPS_DB_LOG_STACK_MAX,
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        raise ValueError(f'Logging settings must be positive: {", ".join(invalid)}')