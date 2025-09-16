import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def _csv_env(key, default=""):
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev")
DEBUG = os.getenv("DJANGO_DEBUG", "False") == "True"

# --- DATABASES ---
DATABASE_URL = os.getenv("DATABASE_URL")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",  # fallback local
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
try:
    import dj_database_url
    if DATABASE_URL:
        DATABASES["default"] = dj_database_url.parse(
            DATABASE_URL, conn_max_age=600, ssl_require=True
        )
except ImportError:
    pass
# --- fin DATABASES ---

# Hosts / CORS / CSRF
ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Añade tu dominio *.up.railway.app y el de Netlify en variables de entorno
CSRF_TRUSTED_ORIGINS = _csv_env("CSRF_TRUSTED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = _csv_env("CORS_ALLOWED_ORIGINS", "")
# (Opcional) para deploy previews de Netlify:
CORS_ALLOWED_ORIGIN_REGEXES = _csv_env("CORS_ALLOWED_ORIGIN_REGEXES", "")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",          # <-- ¡Faltaba!
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # debe ir alto y antes de CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "purchases.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "purchases.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated"
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend"
    ],
}

# (Opcional) JWT por env
from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TTL_MIN", "60"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("JWT_REFRESH_TTL_MIN", "43200"))  # 30 días
    ),
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# I18N / TZ
LANGUAGE_CODE = "es-pe"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Lima")
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Security (Railway detrás de proxy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Cookies seguras solo en producción (HTTP en local)
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True") == "True"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Renderizadores: JSON-only en producción para ahorrar ancho de banda
if not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]

