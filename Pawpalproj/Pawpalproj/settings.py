# Settings for the Pawpal project.
# Django made this file (django-admin startproject, Django 5.2.17).
# All settings: https://docs.djangoproject.com/en/5.2/ref/settings/

import os
from pathlib import Path

import certifi

# Use certifi's list of trusted certificates, so emails to Gmail are sent safely
os.environ["SSL_CERT_FILE"] = certifi.where()

# The project folder. Build file paths from it, e.g. BASE_DIR / 'subdir'
BASE_DIR = Path(__file__).resolve().parent.parent


# These settings are for development only, not for a live website
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# On a live website, keep the secret key private
SECRET_KEY = "django-insecure-6w#lw^a-88&cvunaz_nwepmgn0te!y^v8v%po5d!=jo)g(i_6#"

# On a live website, turn DEBUG off
DEBUG = True

ALLOWED_HOSTS = []


# Apps used in this project

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "user",
    "inventory",
    "payment",
    "service",
    "review",
    "sitting",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",  # must come before our own middleware (it needs the session)
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "user.middleware.security_middleware",
]

ROOT_URLCONF = "Pawpalproj.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "Pawpalproj/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "user.views.navbar",  # points + cart count for the navbar (in user/views.py)
            ],
        },
    },
]

WSGI_APPLICATION = "Pawpalproj.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Django's password checks
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Language and time zone
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "Pawpalproj/static"]

# The type of id field Django adds to every model
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Send emails with Gmail when the login details are set; otherwise show the OTP in the terminal
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER") or os.getenv("EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv(
    "EMAIL_PASSWORD", ""
)
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER or "no-reply@pawpal.local"
ADMIN_CONTACT_EMAIL = "pawpal.sg.demo@gmail.com"

if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
