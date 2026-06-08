from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import create_monitor_schema
from app.monitor import TrafficMonitor
from app.rwms import RwmsClient
from app.telegram_notifier import TelegramNotifier


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run(settings: Settings) -> None:
    configure_logging(settings.log_level)

    engine = create_async_engine(
        settings.postgres_dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    rwms_client = RwmsClient(addr=settings.rwms_address, port=settings.rwms_port)
    notifier = None
    if settings.telegram_bot_token and settings.telegram_notify_chat_ids:
        notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_ids=settings.telegram_notify_chat_ids,
        )

    try:
        if settings.create_schema:
            await create_monitor_schema(engine)

        monitor = TrafficMonitor(
            session_maker=session_maker,
            rwms_client=rwms_client,
            anomaly_threshold_bytes=settings.anomaly_threshold_bytes,
            auto_block_enabled=settings.auto_block_enabled,
            auto_block_threshold_bytes=settings.auto_block_threshold_bytes,
            notifier=notifier,
        )
        logging.getLogger("startup").info(
            "started traffic monitor: interval=%ss anomaly_threshold=%s "
            "auto_block=%s telegram_notifications=%s",
            settings.interval_seconds,
            settings.anomaly_threshold_bytes,
            settings.auto_block_enabled,
            notifier is not None,
        )
        await monitor.run_forever(settings.interval_seconds)
    finally:
        await rwms_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run(Settings.from_env()))
