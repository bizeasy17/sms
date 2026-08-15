import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("SECRET_KEY", "financial-screening-uat-local-only")
DEBUG = os.getenv("DEBUG", "0") == "1"
ALLOWED_HOSTS = [item.strip() for item in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if item.strip()]
ROOT_URLCONF = "financial_screening_service.urls"
MIDDLEWARE = []
INSTALLED_APPS = ["financial_screening.apps.FinancialScreeningConfig"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("FINANCIAL_DB_NAME", "smartinvestor_earnings_uat"),
        "USER": os.getenv("FINANCIAL_DB_USER", "postgres"),
        "PASSWORD": os.getenv("FINANCIAL_DB_PASSWORD", "postgres"),
        "HOST": os.getenv("FINANCIAL_DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("FINANCIAL_DB_PORT", "5432"),
        "OPTIONS": {"options": "-c default_transaction_read_only=on"},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"