import logging
import os
import sys

from logging.config import dictConfig
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import sentry_sdk

from pydantic import BaseSettings, HttpUrl, PostgresDsn, validator
from pydantic.validators import str_validator
from redis import Redis
from retry_tasks_lib.settings import load_settings
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from vela.core.key_vault import KeyVault
from vela.version import __version__

if TYPE_CHECKING:  # pragma: no cover
    from pydantic.typing import CallableGenerator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LogLevel(str):  # pragma: no cover
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        field_schema.update(type="string", format="log_level")

    @classmethod
    def __get_validators__(cls) -> "CallableGenerator":
        yield str_validator
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        v = value.upper()
        if v not in ("CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"):
            raise ValueError(f"{value} is not a valid LOG_LEVEL value")

        return v


class Settings(BaseSettings):  # pragma: no cover
    API_PREFIX: str = "/retailers"
    TESTING: bool = False
    SQL_DEBUG: bool = False

    @validator("TESTING")
    @classmethod
    def is_test(cls, v: bool) -> bool:
        command = sys.argv[0]

        if command == "poetry":
            command = sys.argv[2] if len(sys.argv) > 2 else "None"

        return True if "test" in command else v

    MIGRATING: bool = False

    @validator("MIGRATING")
    @classmethod
    def is_migration(cls, v: bool) -> bool:
        command = sys.argv[0]

        return True if "alembic" in command else v

    PROJECT_NAME: str = "vela"
    ROOT_LOG_LEVEL: LogLevel | None = None
    QUERY_LOG_LEVEL: LogLevel | None = None
    LOG_FORMATTER: Literal["json", "brief"] = "json"

    SENTRY_DSN: HttpUrl | None = None
    SENTRY_ENV: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @validator("SENTRY_DSN", pre=True)
    @classmethod
    def sentry_dsn_can_be_blank(cls, v: str) -> str | None:
        return None if v is not None and not v else v

    @validator("SENTRY_TRACES_SAMPLE_RATE")
    @classmethod
    def validate_sentry_traces_sample_rate(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("SENTRY_TRACES_SAMPLE_RATE must be between 0.0 and 1.0")
        return v

    USE_NULL_POOL: bool = False
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "vela"
    SQLALCHEMY_DATABASE_URI: str = ""
    SQLALCHEMY_DATABASE_URI_ASYNC: str = ""
    DB_CONNECTION_RETRY_TIMES: int = 3

    @validator("SQLALCHEMY_DATABASE_URI", pre=True)
    @classmethod
    def assemble_db_connection(cls, v: str, values: dict[str, Any]) -> Any:
        db_uri = (
            v.format(values["POSTGRES_DB"])
            if v
            else PostgresDsn.build(
                scheme="postgresql",
                user=values.get("POSTGRES_USER"),
                password=values.get("POSTGRES_PASSWORD"),
                host=values.get("POSTGRES_HOST"),
                port=values.get("POSTGRES_PORT"),
                path="/" + values.get("POSTGRES_DB", ""),
            )
        )
        if values["TESTING"]:
            parsed_uri = urlparse(db_uri)
            db_uri = parsed_uri._replace(path=f"{parsed_uri.path}_test").geturl()

        return db_uri

    @validator("SQLALCHEMY_DATABASE_URI_ASYNC", pre=True)
    @classmethod
    def adapt_db_connection_to_async(cls, v: str, values: dict[str, Any]) -> Any:
        return (
            v.format(values["POSTGRES_DB"])
            if v
            else (
                values["SQLALCHEMY_DATABASE_URI"]
                .replace("postgresql://", "postgresql+asyncpg://")
                .replace("sslmode=", "ssl=")
            )
        )

    KEY_VAULT_URI: str = "https://bink-uksouth-dev-com.vault.azure.net/"

    VELA_API_AUTH_TOKEN: str | None = None

    @validator("VELA_API_AUTH_TOKEN")
    @classmethod
    def fetch_vela_api_auth_token(cls, v: str | None, values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-vela-api-auth-token")

        raise KeyError("required var KEY_VAULT_URI is not set.")

    POLARIS_API_AUTH_TOKEN: str | None = None

    @validator("POLARIS_API_AUTH_TOKEN")
    @classmethod
    def fetch_polaris_api_auth_token(cls, v: str | None, values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-polaris-api-auth-token")

        raise KeyError("required var KEY_VAULT_URI is not set.")

    POLARIS_HOST: str = "http://polaris-api"
    POLARIS_BASE_URL: str = ""

    @validator("POLARIS_BASE_URL")
    @classmethod
    def polaris_base_url(cls, v: str, values: dict[str, Any]) -> str:
        return v or f"{values['POLARIS_HOST']}/loyalty"

    REDIS_URL: str

    @validator("REDIS_URL")
    @classmethod
    def assemble_redis_url(cls, v: str, values: dict[str, Any]) -> str:

        if values["TESTING"]:
            base_url, db_n = v.rsplit("/", 1)
            return f"{base_url}/{int(db_n) + 1}"

        return v

    REWARD_ADJUSTMENT_TASK_NAME: str = "reward-adjustment"
    REWARD_STATUS_ADJUSTMENT_TASK_NAME = "reward-status-adjustment"
    REWARD_CANCELLATION_TASK_NAME = "cancel-account-holder-rewards"
    CREATE_CAMPAIGN_BALANCES_TASK_NAME = "create-campaign-balances"
    DELETE_CAMPAIGN_BALANCES_TASK_NAME = "delete-campaign-balances"
    PENDING_REWARDS_TASK_NAME = "convert-or-delete-pending-rewards"

    TASK_MAX_RETRIES: int = 6
    TASK_RETRY_BACKOFF_BASE: float = 3.0
    TASK_QUEUE_PREFIX: str = "vela:"
    TASK_QUEUES: list[str] | None = None
    PROMETHEUS_HTTP_SERVER_PORT: int = 9100

    @validator("TASK_QUEUES")
    @classmethod
    def task_queues(cls, v: list[str] | None, values: dict[str, Any]) -> Any:
        if v and isinstance(v, list):
            return v
        return (values["TASK_QUEUE_PREFIX"] + name for name in ("high", "default", "low"))

    CARINA_API_AUTH_TOKEN: str | None = None

    @validator("CARINA_API_AUTH_TOKEN")
    @classmethod
    def fetch_carina_api_auth_token(cls, v: str | None, values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-carina-api-auth-token")

        raise KeyError("required var KEY_VAULT_URI is not set.")

    CARINA_HOST: str = "http://carina-api"
    CARINA_BASE_URL: str = ""

    @validator("CARINA_BASE_URL")
    @classmethod
    def carina_base_url(cls, v: str, values: dict[str, Any]) -> str:
        return v or f"{values['CARINA_HOST']}/rewards"

    REPORT_ANOMALOUS_TASKS_SCHEDULE: str = "*/10 * * * *"
    REPORT_TASKS_SUMMARY_SCHEDULE: str = "5,20,35,50 */1 * * *"
    REPORT_JOB_QUEUE_LENGTH_SCHEDULE: str = "*/10 * * * *"
    TASK_CLEANUP_SCHEDULE: str = "0 1 * * *"
    TASK_DATA_RETENTION_DAYS: int = 180
    REDIS_KEY_PREFIX: str = "vela:"
    ACTIVATE_TASKS_METRICS: bool = True

    RABBITMQ_URI: str = "amqp://guest:guest@localhost:5672//"
    MESSAGE_EXCHANGE_NAME: str = "hubble-activities"

    class Config:
        case_sensitive = True
        # env var settings priority ie priority 1 will override priority 2:
        # 1 - env vars already loaded (ie the one passed in by kubernetes)
        # 2 - env vars read from *local.env file
        # 3 - values assigned directly in the Settings class
        env_file = os.path.join(BASE_DIR, "local.env")
        env_file_encoding = "utf-8"


settings = Settings()
load_settings(settings)

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "brief": {"format": "%(levelname)s:     %(asctime)s - %(message)s"},
            "json": {"()": "vela.core.reporting.JSONFormatter"},
        },
        "handlers": {
            "stderr": {
                "level": logging.NOTSET,
                "class": "logging.StreamHandler",
                "stream": sys.stderr,
                "formatter": settings.LOG_FORMATTER,
            },
            "stdout": {
                "level": logging.NOTSET,
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": settings.LOG_FORMATTER,
            },
        },
        "loggers": {
            "root": {
                "level": settings.ROOT_LOG_LEVEL or logging.INFO,
                "handlers": ["stdout"],
            },
            "uvicorn": {
                "propagate": False,
                "handlers": ["stdout"],
            },
            "sqlalchemy.engine": {
                "level": settings.QUERY_LOG_LEVEL or logging.WARN,
            },
            "alembic": {
                "level": "INFO",
                "handlers": ["stderr"],
                "propagate": False,
            },
        },
    }
)

# this will decode responses:
# >>> redis.set('test', 'hello')
# True
# >>> redis.get('test')
# 'hello'
redis = Redis.from_url(
    settings.REDIS_URL,
    socket_connect_timeout=3,
    socket_keepalive=True,
    retry_on_timeout=False,
    decode_responses=True,
)

# used for RQ:
# this will not decode responses:
# >>> redis.set('test', 'hello')
# True
# >>> redis.get('test')
# b'hello'
redis_raw = Redis.from_url(
    settings.REDIS_URL,
    socket_connect_timeout=3,
    socket_keepalive=True,
    retry_on_timeout=False,
)


if settings.SENTRY_DSN:  # pragma: no cover
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENV,
        integrations=[
            RedisIntegration(),
            SqlalchemyIntegration(),
        ],
        release=__version__,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )
