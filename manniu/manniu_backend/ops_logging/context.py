import logging
import os
import socket
from uuid import UUID

from django.utils import timezone

from ops_logging.runtime import current_correlation_id, current_run_id
from ops_logging.sanitizer import sanitize_text, sanitize_value


logger = logging.getLogger(__name__)


class LogRunContext:
    def __init__(
        self,
        *,
        run_type,
        name,
        trigger='MANUAL',
        correlation_id=None,
        parameters=None,
        metadata=None,
    ):
        self.run_type = run_type
        self.name = name
        self.trigger = trigger
        self.correlation_id = correlation_id
        self.parameters = parameters or {}
        self.metadata = metadata or {}
        self.run = None
        self._started_at = None
        self._run_token = None
        self._correlation_token = None

    def __enter__(self):
        from ops_logging.models import LogRun

        self._started_at = timezone.now()
        parent_run_id = _parent_run_id_from_environment()
        try:
            self.run = LogRun.objects.create(
                parent_run_id=parent_run_id,
                run_type=self.run_type,
                name=self.name[:96],
                status=LogRun.Status.RUNNING,
                trigger=self.trigger,
                correlation_id=(self.correlation_id or '')[:64] or None,
                started_at=self._started_at,
                heartbeat_at=self._started_at,
                host_name=socket.gethostname()[:128],
                process_id=os.getpid(),
                parameters=sanitize_value(self.parameters),
                metadata=sanitize_value(self.metadata),
            )
        except Exception as exc:
            self.run = None
            logging.getLogger('ops_logging.fallback').warning(
                'Unable to create log run: %s',
                sanitize_text(exc, 500),
            )
        run_id = self.run.id if self.run else None
        self._run_token = current_run_id.set(run_id)
        self._correlation_token = current_correlation_id.set(self.correlation_id)
        return self

    def __exit__(self, exception_type, exception, traceback):
        try:
            if self.run:
                from ops_logging.models import LogRun

                finished_at = timezone.now()
                if exception_type is None:
                    status = LogRun.Status.SUCCEEDED
                    exit_code = 0
                    summary = self.run.summary
                elif issubclass(exception_type, (KeyboardInterrupt, SystemExit)):
                    status = LogRun.Status.CANCELLED
                    exit_code = getattr(exception, 'code', 130)
                    exit_code = exit_code if isinstance(exit_code, int) else 130
                    summary = sanitize_text(exception, 1000)
                else:
                    status = LogRun.Status.FAILED
                    exit_code = 1
                    summary = sanitize_text(exception, 1000)
                    logger.error(
                        'Run failed: %s',
                        self.name,
                        exc_info=(exception_type, exception, traceback),
                        extra={
                            'event_code': 'ops.run.failed',
                            'context': {'run_name': self.name},
                        },
                    )
                self.run.status = status
                self.run.finished_at = finished_at
                self.run.heartbeat_at = finished_at
                self.run.duration_ms = int((finished_at - self._started_at).total_seconds() * 1000)
                self.run.exit_code = exit_code
                self.run.summary = summary
                self.run.save(
                    update_fields=[
                        'status',
                        'finished_at',
                        'heartbeat_at',
                        'duration_ms',
                        'exit_code',
                        'summary',
                    ]
                )
        except Exception as update_error:
            logging.getLogger('ops_logging.fallback').warning(
                'Unable to finalize log run: %s',
                sanitize_text(update_error, 500),
            )
        finally:
            if self._correlation_token is not None:
                current_correlation_id.reset(self._correlation_token)
            if self._run_token is not None:
                current_run_id.reset(self._run_token)
        return False

    @property
    def id(self):
        return self.run.id if self.run else None

    def set_counters(self, **counters):
        if not self.run:
            return
        self.run.counters = sanitize_value(counters)
        self.run.save(update_fields=['counters'])

    def set_summary(self, summary):
        if not self.run:
            return
        self.run.summary = sanitize_text(summary, 4000)


def log_run(**kwargs):
    return LogRunContext(**kwargs)


def _parent_run_id_from_environment():
    value = os.environ.get('MANNIU_PARENT_RUN_ID', '').strip()
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None