from __future__ import annotations

import os
from dataclasses import dataclass


GIB = 1024 * 1024 * 1024


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    log_level: str
    interval_seconds: int
    rwms_address: str
    rwms_port: int
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_db: str
    anomaly_threshold_bytes: int
    auto_block_enabled: bool
    auto_block_threshold_bytes: int
    create_schema: bool

    @classmethod
    def from_env(cls) -> "Settings":
        rwms_address = _get_str("REMNA_RWMS_ADDR", _get_str("MI_UN_RWMS_ADDR"))
        rwms_port = _get_int("REMNA_RWMS_PORT", _get_int("MI_UN_RWMS_PORT", 0))
        pg_host = _get_str("REMNA_POSTGRES_HOST", _get_str("MI_UN_POSTGRES_HOST"))
        pg_user = _get_str("REMNA_POSTGRES_USER", _get_str("MI_UN_POSTGRES_USER"))
        pg_password = _get_str(
            "REMNA_POSTGRES_PASSWORD",
            _get_str("MI_UN_POSTGRES_PASSWORD"),
        )
        pg_db = _get_str("REMNA_POSTGRES_DB", _get_str("MI_UN_POSTGRES_DB"))

        missing = [
            name
            for name, value in {
                "REMNA_RWMS_ADDR": rwms_address,
                "REMNA_RWMS_PORT": rwms_port,
                "REMNA_POSTGRES_HOST": pg_host,
                "REMNA_POSTGRES_USER": pg_user,
                "REMNA_POSTGRES_PASSWORD": pg_password,
                "REMNA_POSTGRES_DB": pg_db,
            }.items()
            if value in (None, "", 0)
        ]
        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(
            log_level=_get_str("TRAFFIC_MONITOR_LOG_LEVEL", "info") or "info",
            interval_seconds=_get_int("TRAFFIC_MONITOR_INTERVAL_SECONDS", 600),
            rwms_address=rwms_address or "",
            rwms_port=rwms_port,
            pg_host=pg_host or "",
            pg_port=_get_int(
                "REMNA_POSTGRES_PORT",
                _get_int("MI_UN_POSTGRES_PORT", 5432),
            ),
            pg_user=pg_user or "",
            pg_password=pg_password or "",
            pg_db=pg_db or "",
            anomaly_threshold_bytes=_get_int(
                "TRAFFIC_MONITOR_ANOMALY_THRESHOLD_BYTES",
                200 * GIB,
            ),
            auto_block_enabled=_get_bool("TRAFFIC_MONITOR_AUTO_BLOCK_ENABLED"),
            auto_block_threshold_bytes=_get_int(
                "TRAFFIC_MONITOR_AUTO_BLOCK_THRESHOLD_BYTES",
                500 * GIB,
            ),
            create_schema=_get_bool("TRAFFIC_MONITOR_CREATE_SCHEMA"),
        )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )
