"""
Django settings for the Kizuna payment gateway.
"""
import os
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Core ───────────────────────────────────────────────
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())
APPEND_SLASH = True
ROOT_URLCONF = "kizuna.urls"
WSGI_APPLICATION = "kizuna.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "mirai.User"

# ─── Apps ───────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    "corsheaders",

    "mirai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─── Database ───────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# ─── Cache / Celery (throttling, reconciliation, webhook retries) ───
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config("REDIS_URL", default="redis://127.0.0.1:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_ENABLE_UTC = True
CELERY_TIMEZONE = "Africa/Dar_es_Salaam"

# ─── Auth ───────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=config("ACCESS_TOKEN_LIFETIME", default=24, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=config("REFRESH_TOKEN_LIFETIME", default=48, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("SIGNING_KEY"),
}

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "mirai.utils.custom_exception.custom_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "1000/hour"},
    "DATE_FORMAT": "%d-%m-%Y",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Kizuna Payments API",
    "DESCRIPTION": "Mobile money collections for Tanzanian merchants",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/",
}

# ─── CORS (only for browser clients; server-to-server calls ignore it) ───
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-payment-key",
    "idempotency-key",
]

# ─── i18n / time ────────────────────────────────────────
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("sw", "Swahili")]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_TZ = True

# ─── Static / media ─────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ─── Payment providers ──────────────────────────────────
TEMBO_ACCOUNT_ID = config("TEMBO_ACCOUNT_ID")
TEMBO_SECRET_KEY = config("TEMBO_SECRET_KEY")
TEMBO_COLLECTION_URL = config("TEMBO_COLLECTION_URL")
TEMBO_COLLECTION_STATUS_URL = config("TEMBO_COLLECTION_STATUS_URL")
TEMBO_CALLBACK_URL = config("TEMBO_CALLBACK_URL")      # your endpoint that Tembo calls

SNIPPE_API_KEY = config("SNIPPE_API_KEY")
SNIPPE_BASE_URL = config("SNIPPE_BASE_URL")
SNIPPE_WEBHOOK_URL = config("SNIPPE_WEBHOOK_URL")

COLLECTION_GATEWAY_PRIORITY = ["tembo", "snippe"]

# ─── SMS (keep only if this project sends notifications) ───
SINGLE_SMS_API_URL = config("SINGLE_SMS_API_URL", default="")
MULTIPLE_SMS_API_URL = config("MULTIPLE_SMS_API_URL", default="")

# ─── Production security (turned on when DEBUG is False) ───
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")