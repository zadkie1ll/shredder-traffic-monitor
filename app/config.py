from __future__ import annotations

import os
from dataclasses import dataclass

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


def _get_int_list(*names: str) -> list[int]:
    raw_values = [os.getenv(name, "") for name in names]
    values = ",".join(value for value in raw_values if value)
    if not values:
        return []

    result = []
    for item in values.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError as exc:
            raise ValueError(f"{names[0]} must contain integer Telegram ids") from exc

    return result


@dataclass(frozen=True)
class Settings:
    log_level: str
    interval_seconds: int
    rwms_page_size: int
    rwms_address: str
    rwms_port: int
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_db: str
    alert_speed_mbps: int
    auto_block_enabled: bool
    auto_block_speed_mbps: int
    create_schema: bool
    telegram_bot_token: str | None
    telegram_notify_chat_ids: list[int]

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
            rwms_page_size=_get_int("TRAFFIC_MONITOR_RWMS_PAGE_SIZE", 500),
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
            alert_speed_mbps=_get_int("TRAFFIC_MONITOR_ALERT_SPEED_MBPS", 100),
            auto_block_enabled=_get_bool("TRAFFIC_MONITOR_AUTO_BLOCK_ENABLED"),
            auto_block_speed_mbps=_get_int(
                "TRAFFIC_MONITOR_AUTO_BLOCK_SPEED_MBPS",
                200,
            ),
            create_schema=_get_bool("TRAFFIC_MONITOR_CREATE_SCHEMA"),
            telegram_bot_token=_get_str(
                "TRAFFIC_MONITOR_TELEGRAM_BOT_TOKEN",
                _get_str("MI_VPN_BOT_TOKEN"),
            ),
            telegram_notify_chat_ids=_get_int_list(
                "TRAFFIC_MONITOR_TELEGRAM_NOTIFY_CHAT_IDS",
                "TRAFFIC_MONITOR_TELEGRAM_NOTIFY_CHAT_ID",
            ),
        )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )
