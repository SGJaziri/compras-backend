# purchases/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url
from datetime import timedelta

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def _csv_env(key, default=""):
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

# --- Core ---
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev")
DEBUG = os.getenv("DJANGO_DEBUG", "False") == "True"

# --- Database ---
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        ssl_require=(os.getenv("DB_SSL_REQUIRE", "False") == "True"),
    )
}

# --- Hosts / CORS / CSRF ---
ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "")  # ej: "localhost,127.0.0.1,tuapp.up.railway.app"
CORS_ALLOWED_ORIGINS = _csv_env("CORS_ALLOWED_ORIGINS", "")  # http(s)://dominio.tld
CORS_ALLOWED_ORIGIN_REGEXES = _csv_env("CORS_ALLOWED_ORIGIN_REGEXES", "")  # regex para previews
CSRF_TRUSTED_ORIGINS = _csv_env("CSRF_TRUSTED_ORIGINS", "")  # http(s)://dominio.tld
CORS_ALLOW_CREDENTIALS = True

# Permitir OPTIONS / headers típicos de fetch + Authorization
CORS_ALLOW_METHODS = [
    "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
]
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# En desarrollo, si no configuraste dominios, permite todo (solo DEBUG)
if DEBUG and not (CORS_ALLOWED_ORIGINS or CORS_ALLOWED_ORIGIN_REGEXES):
    CORS_ALLOW_ALL_ORIGINS = True

# --- Apps ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",

    "core",
]

# --- Middleware ---
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    # CORS lo más alto posible y antes de CommonMiddleware/CSRF
    "corsheaders.middleware.CorsMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "purchases.urls"

# --- Templates ---
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # purchase_list.html / purchase_report.html
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

WSGI_APPLICATION = "purchases.wsgi.application"

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Mantén compatibilidad: primero Token (V1), también JWT (posible V2)
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
}

# Renderizadores: JSON-only en producción, Browsable API en DEBUG
if not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]
else:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ]

# (Opcional) JWT si más adelante lo usas / ya lo usas en algunas rutas
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_TTL_MIN", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_REFRESH_TTL_MIN", "43200"))),  # 30 días
}

# --- Trailing slash: evita 301/405 raros cuando el front omite/agrega '/' ---
APPEND_SLASH = True

# --- Password validation ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18N / TZ ---
LANGUAGE_CODE = "es-pe"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Lima")
USE_I18N = True
USE_TZ = True

# --- Static files ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- Seguridad tras proxy (Railway/Netlify) ---
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookies y redirecciones seguras
if DEBUG:
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
    SECURE_PROXY_SSL_HEADER = None
    CSRF_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SAMESITE = "Lax"
else:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Para permitir cookies en contextos cross-site (si usas sesión/cookies desde otro dominio)
    CSRF_COOKIE_SAMESITE = "None"
    SESSION_COOKIE_SAMESITE = "None"
    # Activa HSTS si tu dominio ya sirve 100% en HTTPS
    # SECURE_HSTS_SECONDS = 31536000
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True
