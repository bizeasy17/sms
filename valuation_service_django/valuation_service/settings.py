import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "valuation-service-dev-key")
DEBUG = os.getenv("DEBUG", "True").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "valuation_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "valuation_service.urls"
TEMPLATES = []
WSGI_APPLICATION = "valuation_service.wsgi.application"
ASGI_APPLICATION = "valuation_service.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": os.getenv("DB_NAME", "valuation_service"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

SOURCE_DB_NAME = os.getenv("SOURCE_DB_NAME", "").strip()
if SOURCE_DB_NAME:
    DATABASES["source"] = {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": SOURCE_DB_NAME,
        "USER": os.getenv("SOURCE_DB_USER", os.getenv("DB_USER", "postgres")),
        "PASSWORD": os.getenv("SOURCE_DB_PASSWORD", os.getenv("DB_PASSWORD", "postgres")),
        "HOST": os.getenv("SOURCE_DB_HOST", os.getenv("DB_HOST", "localhost")),
        "PORT": os.getenv("SOURCE_DB_PORT", os.getenv("DB_PORT", "5432")),
    }

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOW_ALL_ORIGINS = True

FEISHU_BOT_WEBHOOK = os.getenv("FEISHU_BOT_WEBHOOK", "").strip()

ENABLE_LIVE_VALUATION_FALLBACK = os.getenv("ENABLE_LIVE_VALUATION_FALLBACK", "True").lower() in {"1", "true", "yes"}
ENABLE_TUSHARE_FINANCIAL_FALLBACK = os.getenv("ENABLE_TUSHARE_FINANCIAL_FALLBACK", "True").lower() in {"1", "true", "yes"}
