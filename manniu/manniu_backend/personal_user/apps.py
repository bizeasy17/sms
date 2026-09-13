from django.apps import AppConfig


class PersonalUserConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'personal_user'
    verbose_name = 'Personal User'