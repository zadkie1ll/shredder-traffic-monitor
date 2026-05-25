from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import UserTrafficAnomaly
from common.models.db import User


@dataclass(frozen=True)
class TrafficMonitorResult:
    total_rwms_users: int
    matched_users: int
    created_snapshots: int
    updated_snapshots: int
    suspicious_users: int
    blocked_users: int


class TrafficMonitor:
    def __init__(
        self,
        session_maker: async_sessionmaker,
        rwms_client,
        anomaly_threshold_bytes: int,
        auto_block_enabled: bool = False,
        auto_block_threshold_bytes: int | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._rwms_client = rwms_client
        self._anomaly_threshold_bytes = anomaly_threshold_bytes
        self._auto_block_enabled = auto_block_enabled
        self._auto_block_threshold_bytes = (
            auto_block_threshold_bytes
            if auto_block_threshold_bytes is not None
            else anomaly_threshold_bytes
        )
        self._log = logging.getLogger(self.__class__.__name__)

    async def run_forever(self, interval_seconds: int) -> None:
        while True:
            try:
                result = await self.run_once()
                self._log.info("traffic monitor result: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log.exception("traffic monitor iteration failed")

            await asyncio.sleep(interval_seconds)

    async def run_once(self) -> TrafficMonitorResult:
        rwms_users = await self._get_all_rwms_users()
        if not rwms_users:
            self._log.warning("RWMS returned no users; skipping traffic check")
            return TrafficMonitorResult(0, 0, 0, 0, 0, 0)

        rwms_by_username = {
            user.username: user for user in rwms_users if getattr(user, "username", "")
        }

        async with self._session_maker() as session:
            users_result = await session.execute(
                select(User.id, User.username).where(
                    User.username.in_(rwms_by_username.keys())
                )
            )
            users = [(user_id, username) for user_id, username in users_result.all()]
            user_ids = [user_id for user_id, _ in users]

            snapshots_result = await session.execute(
                select(UserTrafficAnomaly).where(
                    UserTrafficAnomaly.user_id.in_(user_ids)
                )
            )
            snapshots_by_user_id = {
                snapshot.user_id: snapshot
                for snapshot in snapshots_result.scalars().all()
            }

            created = 0
            updated = 0
            suspicious = 0
            to_block = []
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            for user_id, username in users:
                rwms_user = rwms_by_username[username]
                current_traffic = int(
                    getattr(rwms_user, "lifetime_used_traffic_bytes", 0) or 0
                )
                snapshot = snapshots_by_user_id.get(user_id)

                if snapshot is None:
                    session.add(
                        UserTrafficAnomaly(
                            user_id=user_id,
                            username=username,
                            last_lifetime_used_traffic_bytes=current_traffic,
                            last_traffic_delta_bytes=0,
                        )
                    )
                    created += 1
                    continue

                previous_traffic = int(snapshot.last_lifetime_used_traffic_bytes or 0)
                delta = max(current_traffic - previous_traffic, 0)
                is_suspicious = delta >= self._anomaly_threshold_bytes
                should_block = (
                    self._auto_block_enabled
                    and delta >= self._auto_block_threshold_bytes
                )

                snapshot.username = username
                snapshot.last_lifetime_used_traffic_bytes = current_traffic
                snapshot.last_traffic_delta_bytes = delta
                snapshot.is_suspicious = is_suspicious
                snapshot.suspicious_reason = (
                    self._build_reason(delta) if is_suspicious else None
                )
                snapshot.detected_at = now if is_suspicious else None
                snapshot.updated_at = now

                if is_suspicious:
                    suspicious += 1
                if should_block and not snapshot.is_blocked:
                    to_block.append((snapshot, rwms_user))

                updated += 1

            await session.commit()

        blocked = 0
        for snapshot, rwms_user in to_block:
            if await self._rwms_client.disable_user(rwms_user):
                blocked += 1
                async with self._session_maker() as session:
                    db_snapshot = await session.get(UserTrafficAnomaly, snapshot.id)
                    if db_snapshot is not None:
                        db_snapshot.is_blocked = True
                        db_snapshot.updated_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        await session.commit()

        return TrafficMonitorResult(
            total_rwms_users=len(rwms_users),
            matched_users=len(users),
            created_snapshots=created,
            updated_snapshots=updated,
            suspicious_users=suspicious,
            blocked_users=blocked,
        )

    async def _get_all_rwms_users(self):
        offset = 0
        count = 1000
        users = []

        while True:
            response = await self._rwms_client.get_all_users(offset=offset, count=count)
            if response is None:
                return []

            users.extend(response.users)
            fetched = len(response.users)
            if fetched == 0:
                break

            offset += fetched
            total = int(getattr(response, "total", 0) or 0)
            if total > 0 and offset >= total:
                break

        return users

    def _build_reason(self, delta: int) -> str:
        return (
            f"traffic delta {delta} bytes reached threshold "
            f"{self._anomaly_threshold_bytes} bytes"
        )
