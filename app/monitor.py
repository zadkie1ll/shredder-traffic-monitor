from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import UserTrafficAnomaly
from app.telegram_notifier import TrafficAnomalyNotification
from common.models.db import User


@dataclass(frozen=True)
class TrafficMonitorResult:
    total_rwms_users: int
    matched_users: int
    created_snapshots: int
    updated_snapshots: int
    suspicious_users: int
    blocked_users: int
    notifications_sent: int
    long_subscription_users: int


class TrafficMonitor:
    def __init__(
        self,
        session_maker: async_sessionmaker,
        rwms_client,
        alert_speed_mbps: int = 100,
        auto_block_enabled: bool = False,
        auto_block_speed_mbps: int = 200,
        auto_block_required_strikes: int = 2,
        rwms_page_size: int = 500,
        notifier=None,
    ) -> None:
        self._session_maker = session_maker
        self._rwms_client = rwms_client
        self._alert_speed_mbps = alert_speed_mbps
        self._auto_block_enabled = auto_block_enabled
        self._auto_block_speed_mbps = auto_block_speed_mbps
        self._auto_block_required_strikes = max(1, auto_block_required_strikes)
        self._rwms_page_size = max(1, rwms_page_size)
        self._notifier = notifier
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
        result = TrafficMonitorResult(0, 0, 0, 0, 0, 0, 0, 0)
        offset = 0
        saw_any_page = False

        while True:
            response = await self._rwms_client.get_all_users(
                offset=offset,
                count=self._rwms_page_size,
            )
            if response is None:
                if not saw_any_page:
                    self._log.warning("RWMS returned no users; skipping traffic check")
                else:
                    self._log.warning(
                        "RWMS returned no users page at offset=%s; "
                        "traffic check stopped after a partial pass",
                        offset,
                    )
                break

            rwms_users = list(response.users)
            fetched = len(rwms_users)
            total = int(getattr(response, "total", 0) or 0)
            if total > 0:
                result = replace(
                    result,
                    total_rwms_users=max(result.total_rwms_users, total),
                )
            else:
                result = replace(
                    result,
                    total_rwms_users=result.total_rwms_users + fetched,
                )

            if fetched == 0:
                break

            saw_any_page = True
            page_result = await self._process_rwms_users_page(rwms_users)
            result = TrafficMonitorResult(
                total_rwms_users=result.total_rwms_users,
                matched_users=result.matched_users + page_result.matched_users,
                created_snapshots=(
                    result.created_snapshots + page_result.created_snapshots
                ),
                updated_snapshots=(
                    result.updated_snapshots + page_result.updated_snapshots
                ),
                suspicious_users=(
                    result.suspicious_users + page_result.suspicious_users
                ),
                blocked_users=result.blocked_users + page_result.blocked_users,
                notifications_sent=(
                    result.notifications_sent + page_result.notifications_sent
                ),
                long_subscription_users=(
                    result.long_subscription_users
                    + page_result.long_subscription_users
                ),
            )

            offset += fetched
            if total > 0 and offset >= total:
                break

        if not saw_any_page:
            return TrafficMonitorResult(0, 0, 0, 0, 0, 0, 0, 0)

        return result

    async def _process_rwms_users_page(self, rwms_users) -> TrafficMonitorResult:
        if not rwms_users:
            return TrafficMonitorResult(0, 0, 0, 0, 0, 0, 0, 0)

        rwms_by_username = {
            user.username: user
            for user in rwms_users
            if getattr(user, "username", "")
        }
        if not rwms_by_username:
            return TrafficMonitorResult(0, 0, 0, 0, 0, 0, 0, 0)

        async with self._session_maker() as session:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            long_subscription_cutoff = now + timedelta(days=365)
            users_result = await session.execute(
                select(User.id, User.username, User.telegram_id, User.expire_at).where(
                    User.username.in_(rwms_by_username.keys())
                )
            )
            matched_rows = users_result.all()
            users = []
            long_subscription_users = 0
            for user_id, username, telegram_id, expire_at in matched_rows:
                is_long_subscription = (
                    expire_at is not None and expire_at >= long_subscription_cutoff
                )
                if is_long_subscription:
                    long_subscription_users += 1
                users.append((user_id, username, telegram_id, is_long_subscription))

            user_ids = [user_id for user_id, _, _, _ in users]
            if not user_ids:
                return TrafficMonitorResult(
                    total_rwms_users=0,
                    matched_users=0,
                    created_snapshots=0,
                    updated_snapshots=0,
                    suspicious_users=0,
                    blocked_users=0,
                    notifications_sent=0,
                    long_subscription_users=(
                        long_subscription_users
                    ),
                )

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
            anomaly_notifications: list[TrafficAnomalyNotification] = []

            for user_id, username, telegram_id, is_long_subscription in users:
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
                previous_checked_at = snapshot.updated_at or snapshot.created_at or now
                elapsed_seconds = max((now - previous_checked_at).total_seconds(), 1)
                average_speed_mbps = self._calculate_speed_mbps(
                    delta,
                    elapsed_seconds,
                )
                is_suspicious = average_speed_mbps >= self._alert_speed_mbps
                exceeds_auto_block_speed = (
                    average_speed_mbps >= self._auto_block_speed_mbps
                )
                current_strikes = int(snapshot.auto_block_strikes or 0)
                auto_block_strikes = (
                    current_strikes + 1 if exceeds_auto_block_speed else 0
                )
                should_block = (
                    self._auto_block_enabled
                    and auto_block_strikes >= self._auto_block_required_strikes
                )

                snapshot.username = username
                snapshot.last_lifetime_used_traffic_bytes = current_traffic
                snapshot.last_traffic_delta_bytes = delta
                snapshot.auto_block_strikes = auto_block_strikes
                snapshot.is_suspicious = is_suspicious
                suspicious_reason = self._build_reason(
                    delta=delta,
                    elapsed_seconds=elapsed_seconds,
                    average_speed_mbps=average_speed_mbps,
                    auto_block_strikes=auto_block_strikes,
                )
                snapshot.suspicious_reason = suspicious_reason if is_suspicious else None
                snapshot.detected_at = now if is_suspicious else None
                snapshot.updated_at = now

                if is_suspicious and not snapshot.is_blocked:
                    suspicious += 1
                    anomaly_notifications.append(
                        TrafficAnomalyNotification(
                            username=username,
                            user_id=user_id,
                            telegram_id=telegram_id,
                            previous_traffic_bytes=previous_traffic,
                            current_traffic_bytes=current_traffic,
                            delta_bytes=delta,
                            average_speed_mbps=average_speed_mbps,
                            speed_threshold_mbps=self._alert_speed_mbps,
                            reason=suspicious_reason,
                            should_block=should_block,
                            blocked=bool(snapshot.is_blocked),
                            detected_at=now,
                        )
                    )
                if should_block and not snapshot.is_blocked:
                    notification_index = (
                        len(anomaly_notifications) - 1 if is_suspicious else None
                    )
                    to_block.append((snapshot, rwms_user, notification_index))

                updated += 1

            await session.commit()

        blocked = 0
        for snapshot, rwms_user, notification_index in to_block:
            if await self._rwms_client.disable_user(rwms_user):
                blocked += 1
                if notification_index is not None:
                    notification = anomaly_notifications[notification_index]
                    anomaly_notifications[notification_index] = replace(
                        notification,
                        blocked=True,
                    )
                async with self._session_maker() as session:
                    db_snapshot = await session.get(UserTrafficAnomaly, snapshot.id)
                    if db_snapshot is not None:
                        db_snapshot.is_blocked = True
                        db_snapshot.updated_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        await session.commit()

        notifications_sent = await self._notify_anomalies(anomaly_notifications)

        return TrafficMonitorResult(
            total_rwms_users=0,
            matched_users=len(users),
            created_snapshots=created,
            updated_snapshots=updated,
            suspicious_users=suspicious,
            blocked_users=blocked,
            notifications_sent=notifications_sent,
            long_subscription_users=long_subscription_users,
        )

    @staticmethod
    def _calculate_speed_mbps(delta_bytes: int, elapsed_seconds: float) -> float:
        return (delta_bytes * 8) / elapsed_seconds / 1_000_000

    def _build_reason(
        self,
        delta: int,
        elapsed_seconds: float,
        average_speed_mbps: float,
        auto_block_strikes: int,
    ) -> str:
        return (
            f"average speed {average_speed_mbps:.2f} Mbps over "
            f"{elapsed_seconds:.0f}s reached threshold "
            f"{self._alert_speed_mbps} Mbps; delta={delta} bytes; "
            f"auto_block_strikes={auto_block_strikes}/"
            f"{self._auto_block_required_strikes}"
        )

    async def _notify_anomalies(
        self,
        anomalies: list[TrafficAnomalyNotification],
    ) -> int:
        if self._notifier is None or not anomalies:
            return 0

        try:
            return await self._notifier.notify_traffic_anomalies(anomalies)
        except Exception:
            self._log.exception("failed to send traffic anomaly notifications")
            return 0
