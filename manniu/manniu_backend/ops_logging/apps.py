from django.apps import AppConfig


class OpsLoggingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ops_logging'
    verbose_name = 'Operations Logging'

    def ready(self):
        from ops_logging.handlers import configure_database_logging

        configure_database_logging()