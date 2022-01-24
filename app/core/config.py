import logging
import os
import sys

from logging.config import dictConfig
from typing import TYPE_CHECKING, Any, Optional

import sentry_sdk

from pydantic import BaseSettings, HttpUrl, PostgresDsn, validator
from pydantic.validators import str_validator
from redis import Redis

from app.core.key_vault import KeyVault
from app.version import __version__

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
        if v not in ["CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"]:
            raise ValueError(f"{value} is not a valid LOG_LEVEL value")

        return v


class Settings(BaseSettings):  # pragma: no cover
    API_PREFIX: str = "/bpl/rewards"
    TESTING: bool = False
    SQL_DEBUG: bool = False
    METRICS_DEBUG: bool = False

    @validator("TESTING")
    def is_test(cls, v: bool) -> bool:
        command = sys.argv[0]
        args = sys.argv[1:] if len(sys.argv) > 1 else []

        if "pytest" in command or any("test" in arg for arg in args):
            return True
        return v

    MIGRATING: bool = False

    @validator("MIGRATING")
    def is_migration(cls, v: bool) -> bool:
        command = sys.argv[0]

        if "alembic" in command:
            return True
        return v

    PROJECT_NAME: str = "vela"
    ROOT_LOG_LEVEL: Optional[LogLevel] = None
    QUERY_LOG_LEVEL: Optional[LogLevel] = None
    LOG_FORMATTER: str = "json"

    @validator("LOG_FORMATTER")
    def validate_formatter(cls, v: str) -> Optional[str]:
        if v not in ["json", "brief"]:
            raise ValueError(f'"{v}" is not a valid LOG_FORMATTER value, choices are [json, brief]')
        return v

    SENTRY_DSN: Optional[HttpUrl] = None
    SENTRY_ENV: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @validator("SENTRY_DSN", pre=True)
    def sentry_dsn_can_be_blank(cls, v: str) -> Optional[str]:
        if v is not None and len(v) == 0:
            return None
        return v

    @validator("SENTRY_TRACES_SAMPLE_RATE")
    def validate_sentry_traces_sample_rate(cls, v: float) -> float:
        if not (0 <= v <= 1):
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
    def assemble_db_connection(cls, v: str, values: dict[str, Any]) -> Any:
        if v != "":
            db_uri = v

        else:
            db_uri = PostgresDsn.build(
                scheme="postgresql",
                user=values.get("POSTGRES_USER"),
                password=values.get("POSTGRES_PASSWORD"),
                host=values.get("POSTGRES_HOST"),
                port=values.get("POSTGRES_PORT"),
                path="/" + values.get("POSTGRES_DB", ""),
            )

        if values["TESTING"]:
            db_uri += "_test"

        return db_uri

    @validator("SQLALCHEMY_DATABASE_URI_ASYNC", pre=True)
    def adapt_db_connection_to_async(cls, v: str, values: dict[str, Any]) -> Any:
        if v != "":
            db_uri = v
        else:
            db_uri = (
                values["SQLALCHEMY_DATABASE_URI"]
                .replace("postgresql://", "postgresql+asyncpg://")
                .replace("sslmode=", "ssl=")
            )

        return db_uri

    KEY_VAULT_URI: str = "https://bink-uksouth-dev-com.vault.azure.net/"
    SECRET_KEY: Optional[str] = None

    @validator("SECRET_KEY")
    def fetch_secret_key(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-vela-secret-key")
        else:
            raise KeyError("required var KEY_VAULT_URI is not set.")

    VELA_AUTH_TOKEN: Optional[str] = None

    @validator("VELA_AUTH_TOKEN")
    def fetch_auth_token(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-reward-mgmt-auth-token")
        else:
            raise KeyError("required var KEY_VAULT_URI is not set.")

    POLARIS_AUTH_TOKEN: Optional[str] = None

    @validator("POLARIS_AUTH_TOKEN")
    def fetch_polaris_auth_token(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-customer-mgmt-auth-token")
        else:
            raise KeyError("required var KEY_VAULT_URI is not set.")

    POLARIS_URL: str = "http://polaris-api"
    REDIS_URL: str
    REWARD_ADJUSTMENT_TASK_NAME: str = "reward-adjustment"
    REWARD_STATUS_ADJUSTMENT_TASK_NAME = "reward-status-adjustment"
    CREATE_CAMPAIGN_BALANCES_TASK_NAME = "create-campaign-balances"
    DELETE_CAMPAIGN_BALANCES_TASK_NAME = "delete-campaign-balances"

    TASK_MAX_RETRIES: int = 6
    TASK_RETRY_BACKOFF_BASE: float = 3.0
    TASK_QUEUE_PREFIX: str = "vela:"
    TASK_QUEUES: Optional[list[str]] = None
    PROMETHEUS_HTTP_SERVER_PORT: int = 9100

    @validator("TASK_QUEUES")
    def task_queues(cls, v: Optional[list[str]], values: dict[str, Any]) -> Any:
        if v and isinstance(v, list):
            return v
        return (values["TASK_QUEUE_PREFIX"] + name for name in ("high", "default", "low"))

    CARINA_AUTH_TOKEN: Optional[str] = None

    @validator("CARINA_AUTH_TOKEN")
    def fetch_carina_auth_token(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str) and not values["TESTING"]:
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-voucher-mgmt-auth-token")
        else:
            raise KeyError("required var KEY_VAULT_URI is not set.")

    CARINA_URL: str = "http://carina-api"

    class Config:
        case_sensitive = True
        # env var settings priority ie priority 1 will override priority 2:
        # 1 - env vars already loaded (ie the one passed in by kubernetes)
        # 2 - env vars read from *local.env file
        # 3 - values assigned directly in the Settings class
        env_file = os.path.join(BASE_DIR, "local.env")
        env_file_encoding = "utf-8"


settings = Settings()

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "brief": {"format": "%(levelname)s:     %(asctime)s - %(message)s"},
            "json": {"()": "app.core.reporting.JSONFormatter"},
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
            "sqlalchemy": {
                "level": settings.QUERY_LOG_LEVEL or logging.WARN,
                "qualname": "sqlalchemy.engine",
            },
            "alembic": {
                "level": "INFO",
                "handlers": ["stderr"],
                "propagate": False,
                "qualname": "alembic",
            },
        },
    }
)


redis = Redis.from_url(
    settings.REDIS_URL,
    socket_connect_timeout=3,
    socket_keepalive=True,
    retry_on_timeout=False,
)

if settings.SENTRY_DSN:  # pragma: no cover
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENV,
        release=__version__,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )
