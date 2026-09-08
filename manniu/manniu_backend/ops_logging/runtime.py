from contextvars import ContextVar


current_run_id = ContextVar('ops_log_run_id', default=None)
current_correlation_id = ContextVar('ops_log_correlation_id', default=None)
current_request_id = ContextVar('ops_log_request_id', default=None)