from __future__ import annotations

from common.models.db import Base, UserTrafficAnomaly


async def create_monitor_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[UserTrafficAnomaly.__table__],
        )
