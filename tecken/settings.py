# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.
"""
Django settings for tecken project.
"""
import datetime
import logging
import subprocess
import os

from configurations import Configuration, values
from django.contrib.messages import constants as messages
from dockerflow.version import get_version
from raven.transport.requests import RequestsHTTPTransport


class AWS:
    "AWS configuration"

    AWS_CONFIG = {
        # AWS EC2 configuration
        # 'AWS_REGION': 'us-west-2',
        # 'EC2_KEY_NAME': '20161025-dataops-dev',
    }


class CSP:
    # Django-CSP
    CSP_DEFAULT_SRC = (
        "'self'",
    )
    CSP_FONT_SRC = (
        "'self'",
        # 'http://*.mozilla.net',
        # 'https://*.mozilla.net',
        # 'http://*.mozilla.org',
        # 'https://*.mozilla.org',
    )
    CSP_IMG_SRC = (
        "'self'",
        # "data:",
        # 'http://*.mozilla.net',
        # 'https://*.mozilla.net',
        # 'http://*.mozilla.org',
        # 'https://*.mozilla.org',
        # 'https://sentry.prod.mozaws.net',
    )
    CSP_SCRIPT_SRC = (
        "'self'",
        # 'http://*.mozilla.org',
        # 'https://*.mozilla.org',
        # 'http://*.mozilla.net',
        # 'https://*.mozilla.net',
        # 'https://cdn.ravenjs.com',
    )
    CSP_STYLE_SRC = (
        "'self'",
        "'unsafe-inline'",
        # 'http://*.mozilla.org',
        # 'https://*.mozilla.org',
        # 'http://*.mozilla.net',
        # 'https://*.mozilla.net',
    )
    CSP_CONNECT_SRC = (
        "'self'",
        # 'https://sentry.prod.mozaws.net',
    )
    CSP_OBJECT_SRC = (
        "'none'",
    )


class Celery:

    # Use the django_celery_results database backend.
    CELERY_RESULT_BACKEND = 'django-db'

    # Throw away task results after two weeks, for debugging purposes.
    CELERY_RESULT_EXPIRES = datetime.timedelta(days=14)

    # Track if a task has been started, not only pending etc.
    CELERY_TASK_TRACK_STARTED = True

    # Add a 5 minute soft timeout to all Celery tasks.
    CELERY_TASK_SOFT_TIME_LIMIT = 60 * 5

    # And a 10 minute hard timeout.
    CELERY_TASK_TIME_LIMIT = CELERY_TASK_SOFT_TIME_LIMIT * 2


class Core(CSP, AWS, Configuration, Celery):
    """Settings that will never change per-environment."""

    # Build paths inside the project like this: os.path.join(BASE_DIR, ...)
    THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(THIS_DIR)

    VERSION = get_version(BASE_DIR)

    # Using the default first site found by django.contrib.sites
    SITE_ID = 1

    INSTALLED_APPS = [
        # Django apps
        'django.contrib.sites',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',

        # Project specific apps
        'tecken.apps.TeckenAppConfig',
        'tecken.symbolicate',
        'tecken.download',
        'tecken.tokens',
        'tecken.upload',

        # Third party apps
        'dockerflow.django',
        'django_celery_results',

        # Third party apps, that need to be listed last
        'mozilla_django_oidc',
    ]

    # June 2017: Notice that we're NOT adding
    # 'mozilla_django_oidc.middleware.RefreshIDToken'. That's because
    # most views in this project are expected to be called as AJAX
    # or from curl. So it doesn't make sense to require every request
    # to refresh the ID token.
    # Once there is a way to do OIDC ID token refreshing without needing
    # the client to redirect, we can enable that.
    # Note also, the ostensible reason for using 'RefreshIDToken' is
    # to check that a once-authenticated user is still a valid user.
    # So if that's "disabled", that's why we have rather short session
    # cookie age.
    MIDDLEWARE_CLASSES = (
        'django.middleware.security.SecurityMiddleware',
        'dockerflow.django.middleware.DockerflowMiddleware',
        # 'whitenoise.middleware.WhiteNoiseMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
        'csp.middleware.CSPMiddleware',
        'tecken.tokens.middleware.APITokenAuthenticationMiddleware',
    )

    ROOT_URLCONF = 'tecken.urls'

    WSGI_APPLICATION = 'tecken.wsgi.application'

    # Add the django-allauth authentication backend.
    AUTHENTICATION_BACKENDS = (
        'django.contrib.auth.backends.ModelBackend',
        'mozilla_django_oidc.auth.OIDCAuthenticationBackend',
    )

    MESSAGE_TAGS = {
        messages.ERROR: 'danger'
    }

    # Internationalization
    # https://docs.djangoproject.com/en/1.9/topics/i18n/
    LANGUAGE_CODE = 'en-us'
    TIME_ZONE = 'UTC'
    USE_I18N = False
    USE_L10N = False
    USE_TZ = True
    DATETIME_FORMAT = 'Y-m-d H:i'  # simplified ISO format since we assume UTC

    STATIC_ROOT = values.Value(default='/opt/static/')
    STATIC_URL = '/static/'

    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'

    # XXX what IS this?
    SILENCED_SYSTEM_CHECKS = [
        'security.W003',  # We're using django-session-csrf
        # We can't set SECURE_HSTS_INCLUDE_SUBDOMAINS since this runs under a
        # mozilla.org subdomain
        'security.W005',
        'security.W009',  # we know the SECRET_KEY is strong
    ]

    TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'OPTIONS': {
                'context_processors': [
                    'django.contrib.auth.context_processors.auth',
                    'django.template.context_processors.debug',
                    'django.template.context_processors.i18n',
                    'django.template.context_processors.media',
                    'django.template.context_processors.static',
                    'django.template.context_processors.tz',
                    'django.template.context_processors.request',
                    'django.contrib.messages.context_processors.messages',
                ],
                'loaders': [
                    'django.template.loaders.filesystem.Loader',
                    'django.template.loaders.app_directories.Loader',
                ],
            }
        },
    ]

    OIDC_RP_CLIENT_ID = values.SecretValue()
    OIDC_RP_CLIENT_SECRET = values.SecretValue()

    OIDC_OP_AUTHORIZATION_ENDPOINT = values.URLValue(
        'https://auth.mozilla.auth0.com/authorize'
    )
    OIDC_OP_TOKEN_ENDPOINT = values.URLValue(
        'https://auth.mozilla.auth0.com/oauth/token'
    )
    OIDC_OP_USER_ENDPOINT = values.URLValue(
        'https://auth.mozilla.auth0.com/userinfo'
    )

    # Keep it quite short because we don't have a practical way to do
    # OIDC ID token renewal for this AJAX and curl heavy app.
    SESSION_COOKIE_AGE = values.IntegerValue(60 * 60 * 24 * 7)

    # Where users get redirected after successfully signing in
    LOGIN_REDIRECT_URL = '/?signedin=true'

    # API Token authentication is off by default until Tecken has
    # gone through a security checklist.
    ENABLE_TOKENS_AUTHENTICATION = values.BooleanValue(False)

    TOKENS_DEFAULT_EXPIRATION_DAYS = values.IntegerValue(365)  # 1 year


class Base(Core):
    """Settings that may change per-environment, some with defaults."""

    SECRET_KEY = values.SecretValue()

    DEBUG = values.BooleanValue(default=False)
    DEBUG_PROPAGATE_EXCEPTIONS = values.BooleanValue(default=False)

    ALLOWED_HOSTS = values.ListValue([])

    DATABASES = values.DatabaseURLValue('postgres://postgres@db/postgres')

    REDIS_URL = values.Value('redis://redis-cache:6379/0')
    REDIS_STORE_URL = values.Value('redis://redis-store:6379/0')

    # Use redis as the Celery broker.
    @property
    def CELERY_BROKER_URL(self):
        return self.REDIS_URL

    @property
    def CACHES(self):
        return {
            'default': {
                'BACKEND': 'django_redis.cache.RedisCache',
                'LOCATION': self.REDIS_URL,
                'OPTIONS': {
                    'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',  # noqa
                    'SERIALIZER': 'django_redis.serializers.msgpack.MSGPackSerializer',  # noqa
                },
            },
            'store': {
                'BACKEND': 'django_redis.cache.RedisCache',
                'LOCATION': self.REDIS_STORE_URL,
                'OPTIONS': {
                    'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',  # noqa
                    'SERIALIZER': 'django_redis.serializers.msgpack.MSGPackSerializer',  # noqa
                },
            },
        }

    LOGGING_USE_JSON = values.BooleanValue(False)

    LOGGING_DEFAULT_LEVEL = values.Value('INFO')

    def LOGGING(self):
        return {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'json': {
                    '()': 'dockerflow.logging.JsonLogFormatter',
                    'logger_name': 'tecken',
                },
                'verbose': {
                    'format': '%(levelname)s %(asctime)s %(name)s %(message)s',
                },
            },
            'handlers': {
                'console': {
                    'level': self.LOGGING_DEFAULT_LEVEL,
                    'class': 'logging.StreamHandler',
                    'formatter': (
                        'json' if self.LOGGING_USE_JSON else 'verbose'
                    ),
                },
                'sentry': {
                    'level': 'ERROR',
                    'class': (
                        'raven.contrib.django.raven_compat.handlers'
                        '.SentryHandler'
                    ),
                },
                'null': {
                    'class': 'logging.NullHandler',
                },
            },
            'root': {
                'level': 'INFO',
                'handlers': ['sentry', 'console'],
            },
            'loggers': {
                'django.db.backends': {
                    'level': 'ERROR',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'django.request': {
                    'level': 'ERROR',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'raven': {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'sentry.errors': {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'tecken': {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'mozilla_django_oidc': {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'celery.task': {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'markus': {
                    'level': 'INFO',
                    'handlers': ['console'],
                    'propagate': False,
                },
                'request.summary': {
                    'handlers': ['console'],
                    'level': 'DEBUG',
                    'propagate': False,
                },
                'django.security.DisallowedHost': {
                    'handlers': ['null'],
                    'propagate': False,
                },
            },
        }

    # The order here matters. Symbol download goes through these one
    # at a time.
    # Ideally you want the one most commonly hit first unless there's a
    # cascading reason you want other buckets first.
    # By default, each URL is assumed to be private!
    # If there's a bucket you want to include that should be accessed
    # by HTTP only, add '?access=public' to the URL.
    # Note that it's empty by default which is actually not OK.
    # For production-like environments this must be something or else
    # Django won't start. (See tecken.apps.TeckenAppConfig)
    #
    SYMBOL_URLS = values.ListValue([])

    # Same as with SYMBOL_URLS, this has to be set to something
    # or else Django won't start.
    UPLOAD_DEFAULT_URL = values.Value()

    # The config is a list of tuples like this:
    # 'email:url' where the email part can be a glob like regex
    # For example '*@example.com:https://s3-us-west-2.amazonaws.com/mybucket'
    # will upload all symbols to a bucket called 'mybucket' for anybody
    # with a @example.com email.

    # This is a config that, typed as a Python dictionary, specifies
    # specific email addresses or patterns to custom URLs.
    # For example '{"peter@example.com": "https://s3.amazonaws.com/mybucket"}'
    # or '{"*@example.com": "https://s3.amazonaws.com/otherbucket"}' for
    # anybody uploading with an @example.com email address.
    UPLOAD_URL_EXCEPTIONS = values.DictValue({})

    # The default prefix for locating all symbols
    SYMBOL_FILE_PREFIX = values.Value('v1')

    # During upload, for each file in the archive, if the extension
    # matches this list, the file gets gzip compressed before uploading.
    COMPRESS_EXTENSIONS = values.ListValue(['sym'])

    # For specific file uploads, override the mimetype.
    # For .sym files, for example, if S3 knows them as 'text/plain'
    # they become really handy to open in a browser and view directly.
    MIME_OVERRIDES = values.DictValue({
        'sym': 'text/plain',
    })

    # Number of seconds to wait for a symbol download. If this
    # trips, no error will be raised and we'll just skip using it
    # as a known symbol file.
    # The value gets cached as an empty dict for one hour.
    SYMBOLS_GET_TIMEOUT = values.Value(5)

    # Individual strings that can't be allowed in any of the lines in the
    # content of a symbols archive file.
    DISALLOWED_SYMBOLS_SNIPPETS = values.ListValue([
        # https://bugzilla.mozilla.org/show_bug.cgi?id=1012672
        'qcom/proprietary',
    ])

    DOCKERFLOW_CHECKS = [
        'dockerflow.django.checks.check_database_connected',
        'dockerflow.django.checks.check_migrations_applied',
        'dockerflow.django.checks.check_redis_connected',
        'tecken.dockerflow_extra.check_redis_store_connected',
        'tecken.dockerflow_extra.check_s3_urls',
    ]

    # This determines how many different symbol keys we store in the
    # global LRU cache object.
    SYMBOLDOWNLOAD_EXISTS_TIMEOUT_MAXSIZE = values.IntegerValue(10000)

    # We use an LRU in-memory cache which means that really popular
    # symbols will almost never be evicted from the cache. But, if
    # we have actually "changed the outside world" (i.e. populating the
    # symbol in S3) we need to force evict it from the LRU cache.
    # This way it's an LRU + TTL cache sort of.
    SYMBOLDOWNLOAD_MAX_TTL_SECONDS = values.IntegerValue(60 * 60)


class Localdev(Base):
    """Configuration to be used during local development and base class
    for testing"""

    # Override some useful developer settings to be True by default.
    ENABLE_TOKENS_AUTHENTICATION = values.BooleanValue(True)
    DEBUG = values.BooleanValue(default=True)
    DEBUG_PROPAGATE_EXCEPTIONS = values.BooleanValue(default=True)

    # When doing localdev, these defaults will suffice. The localstack
    # one forces you to use/test boto3 and the old public symbols URL
    # forces you to use/test the symbol downloader based on requests.get().
    SYMBOL_URLS = values.ListValue([
        'http://localstack-s3:4572/testbucket',
        'https://s3-us-west-2.amazonaws.com/org.mozilla.crash-stats.symbols-public/v1/?access=public',  # noqa
    ])

    # By default, upload all symbols to this when in local dev.
    UPLOAD_DEFAULT_URL = values.Value(
        'http://localstack-s3:4572/testbucket'
    )

    @classmethod
    def post_setup(cls):
        super().post_setup()
        # in case we don't find these AWS config variables in the environment
        # we load them from the .env file
        for param in ('ACCESS_KEY_ID', 'SECRET_ACCESS_KEY', 'DEFAULT_REGION'):
            if param not in os.environ:
                os.environ[param] = values.Value(
                    default='',
                    environ_name=param,
                    environ_prefix='AWS',
                )

    @property
    def VERSION(self):
        output = subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--abbrev=0']
        )
        if output:
            return {'version': output.decode().strip()}
        else:
            return {}

    MARKUS_BACKENDS = [
        # Commented out, but uncomment if you want to see all the
        # metrics sent to markus.
        # {
        #     'class': 'markus.backends.logging.LoggingMetrics',
        # },
        {
            'class': 'markus.backends.datadog.DatadogMetrics',
            'options': {
                'statsd_host': 'statsd',
                'statsd_port': 8125,
                'statsd_namespace': ''
            }
        },
        # {
        #     'class': 'markus.backends.logging.LoggingRollupMetrics',
        #     'options': {
        #         'logger_name': 'markus',
        #         'leader': 'ROLLUP',
        #         'flush_interval': 60
        #     }
        # },

        # Only uncomment this when using that old metricsapp
        # {
        #     'class': 'tecken.markus_extra.CacheMetrics',
        # },
    ]


class Test(Localdev):
    """Configuration to be used during testing"""
    DEBUG = False

    # We might not enable it in certain environments but we definitely
    # want to test the code we have.
    ENABLE_TOKENS_AUTHENTICATION = True

    SECRET_KEY = values.Value('not-so-secret-after-all')

    OIDC_RP_CLIENT_ID = values.Value('not-so-secret-after-all')
    OIDC_RP_CLIENT_SECRET = values.Value('not-so-secret-after-all')

    PASSWORD_HASHERS = (
        'django.contrib.auth.hashers.MD5PasswordHasher',
    )

    SYMBOL_URLS = values.ListValue([
        'https://s3.example.com/public/prefix/?access=public',
        'https://s3.example.com/private/prefix/',
    ])

    AUTHENTICATION_BACKENDS = (
        'django.contrib.auth.backends.ModelBackend',
    )

    SYMBOL_FILE_PREFIX = 'v0'
    UPLOAD_DEFAULT_URL = 'http://s3.example.com/mybucket'
    UPLOAD_URL_EXCEPTIONS = {
        '*@peterbe.com': 'http://s3.example.com/peterbe-com',
    }


class Dev(Base):
    """Configuration to be used in dev server environment"""

    LOGGING_USE_JSON = True

    ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'https'
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = int(datetime.timedelta(days=365).total_seconds())
    SECURE_HSTS_PRELOAD = True
    # Mark session and CSRF cookies as being HTTPS-only.
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    # This is needed to get a CRSF token in /admin
    ANON_ALWAYS = True

    @property
    def DATABASES(self):
        "require encrypted connections to Postgres"
        DATABASES = super().DATABASES.value.copy()
        DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = 'require'
        return DATABASES

    # Sentry setup
    SENTRY_DSN = values.Value(environ_prefix=None)
    SENTRY_PUBLIC_DSN = values.Value(environ_prefix=None)

    MIDDLEWARE_CLASSES = (
        'raven.contrib.django.raven_compat.middleware'
        '.SentryResponseErrorIdMiddleware',
    ) + Base.MIDDLEWARE_CLASSES

    INSTALLED_APPS = Base.INSTALLED_APPS + [
        'raven.contrib.django.raven_compat',
    ]

    SENTRY_CELERY_LOGLEVEL = logging.INFO

    @property
    def RAVEN_CONFIG(self):
        config = {
            'dsn': self.SENTRY_DSN,
            'transport': RequestsHTTPTransport,
        }
        if self.VERSION:
            config['release'] = (
                self.VERSION.get('version') or
                self.VERSION.get('commit') or
                ''
            )
        return config

    # Report CSP reports to this URL that is only available in stage and prod
    CSP_REPORT_URI = '/__cspreport__'

    # Defaulting to 'localhost' here because that's where the Datadog
    # agent is expected to run in production.
    STATSD_HOST = values.Value('localhost')
    STATSD_PORT = values.Value(8125)
    STATSD_NAMESPACE = values.Value('')

    @property
    def MARKUS_BACKENDS(self):
        return [
            {
                'class': 'markus.backends.datadog.DatadogMetrics',
                'options': {
                    'statsd_host': self.STATSD_HOST,
                    'statsd_port': self.STATSD_PORT,
                    'statsd_namespace': self.STATSD_NAMESPACE,
                }
            },
        ]


class Stage(Dev):
    """Configuration to be used in stage environment"""


class Prod(Stage):
    """Configuration to be used in prod environment"""


class Prodlike(Prod):
    """Configuration when you want to run, as if it's in production, but
    in docker."""

    DEBUG = False

    SYMBOL_URLS = Localdev.SYMBOL_URLS
    UPLOAD_DEFAULT_URL = Localdev.UPLOAD_DEFAULT_URL

    # Make it possible to disable this in local prod-like environments
    # but still make it True by default
    LOGGING_USE_JSON = values.BooleanValue(True)

    @property
    def DATABASES(self):
        "Don't require encrypted connections to Postgres"
        DATABASES = super().DATABASES.copy()
        DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = 'disable'
        return DATABASES

    MARKUS_BACKENDS = []

    # If you try to run with prod like settings locally, you most likely
    # have to use a self-signed SSL cert.
    SECURE_HSTS_SECONDS = 60

    if os.environ.get('DJANGO_RUN_INSECURELY', False):  # hackish, but works
        # When running with DJANGO_CONFIGURATION=Prodlike, if you don't want
        # to have to use HTTPS, uncomment these lines:
        ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'http'
        SECURE_SSL_REDIRECT = False
        SECURE_HSTS_SECONDS = 0
        SECURE_HSTS_PRELOAD = False


class Build(Prod):
    """Configuration to be used in build (!) environment"""
    SECRET_KEY = values.Value('not-so-secret-after-all')
