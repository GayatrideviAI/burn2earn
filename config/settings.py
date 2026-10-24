"""Django settings for the Regenerix core platform."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

_DEV_SECRET = "dev-insecure-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_SECRET)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

if not DEBUG and SECRET_KEY == _DEV_SECRET:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is off.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "apps.core",
    "apps.accounts",
    "apps.geography",
    "apps.territory",
    "apps.network",
    "apps.reference",
    "apps.farms",
    "apps.field",
    "apps.demand",
    "apps.operations",
    "apps.ledger",
    "apps.trade",
    "apps.customers",
    "apps.yardops",
    "apps.weightphotos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Picks the language from the visitor's choice (cookie), then their browser.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Records who made a change; must come after AuthenticationMiddleware.
    "apps.core.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "apps.core.context.predictor",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("POSTGRES_DB", "burn2earn"),
        "USER": os.environ.get("POSTGRES_USER", "burn2earn"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "burn2earn"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
# Customer pages can be shown in these languages (names are written in the language itself).
LANGUAGES = [("en", "English"), ("hi", "हिन्दी"), ("pa", "ਪੰਜਾਬੀ")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "field:login"
LOGIN_REDIRECT_URL = "field:dashboard"
LOGOUT_REDIRECT_URL = "field:login"

# The admin map loads its background tiles from OpenStreetMap, which refuses requests
# that carry no Referer. Django's default ("same-origin") strips it for other sites.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Customer stock: how old a physical count may be before it is "overdue", and the days it takes to
# bring in new stock. Both are starting values to adjust with the first pilot customer.
STOCK_VERIFICATION_DAYS = 14
STOCK_REPLENISH_LEAD_DAYS = 14

# ---- Yard heat and stack rules -----------------------------------------------------------------
# The temperature steps follow general hay-safety guidance (about 50 °C normal limit, 65 °C watch
# closely, 70 °C check twice a day and open the stack, 80 °C fire likely). The other numbers are
# starting assumptions. ALL of them must be validated for baled paddy straw with a qualified
# fire-safety partner before anyone relies on them.
# Address of the stand-alone biomass predictor (tools/biomass_predictor). Empty hides the links.
PREDICTOR_URL = os.environ.get("PREDICTOR_URL", "")

YARD_HEAT_WARM_C = 50
YARD_HEAT_WATCH_C = 65
YARD_HEAT_ACT_C = 70
YARD_HEAT_EMERGENCY_C = 80
YARD_HEAT_RISE_C_PER_DAY = 3      # a rise this fast is a warning even below the temperature steps
YARD_READING_MAX_AGE_DAYS = 3     # a pile with no temperature reading for this long is "not checked"
YARD_DAMP_INTAKE_PERCENT = 20     # stacked damper than this at intake
YARD_MAX_STACK_HEIGHT_M = 4       # taller stacks hold heat
YARD_ALERT_ACK_MINUTES = 30       # an alert not acknowledged by now is shown as overdue


# Photos taken in the phone apps (weight-from-photo data collection). Kept outside the code folder's static files.
MEDIA_ROOT = BASE_DIR / "media"
WEIGHT_PHOTO_MAX_BYTES = 8 * 1024 * 1024
# How many photos WITH a weighbridge weight we want per kind before trying a model. This is an
# assumption, not a measured figure; a data scientist should set it once there is real data.
WEIGHT_PHOTO_TARGET_PER_SUBJECT = 300
