from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.monitor import TrafficMonitor
from common.models.db import Base, User, UserTrafficAnomaly


@dataclass
class FakeSquad:
    uuid: str


@dataclass
class FakeRwmsUser:
    username: str
    lifetime_used_traffic_bytes: int
    uuid: str = "rwms-user-uuid"
    active_internal_squads: list[FakeSquad] = field(default_factory=list)


@dataclass
class FakeRwmsResponse:
    users: list[FakeRwmsUser]
    total: int


class FakeRwmsClient:
    def __init__(self, users: list[FakeRwmsUser]) -> None:
        self.users = users
        self.disabled = []

    async def get_all_users(self, offset: int, count: int):
        return FakeRwmsResponse(
            users=self.users[offset : offset + count],
            total=len(self.users),
        )

    async def disable_user(self, user) -> bool:
        self.disabled.append(user.username)
        return True


class FakeNotifier:
    def __init__(self) -> None:
        self.anomalies = []

    async def notify_traffic_anomalies(self, anomalies):
        self.anomalies.extend(anomalies)
        return len(anomalies)


@pytest.fixture()
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, UserTrafficAnomaly.__table__],
        )

    try:
        yield async_sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def add_user(session_maker, user_id: int = 1, username: str = "user-1") -> None:
    async with session_maker() as session:
        session.add(User(id=user_id, telegram_id=user_id, username=username))
        await session.commit()


@pytest.mark.asyncio
async def test_first_seen_user_creates_baseline_without_delta(session_maker):
    await add_user(session_maker)
    rwms = FakeRwmsClient(
        [FakeRwmsUser(username="user-1", lifetime_used_traffic_bytes=100)]
    )
    monitor = TrafficMonitor(session_maker, rwms, anomaly_threshold_bytes=200)

    result = await monitor.run_once()

    async with session_maker() as session:
        snapshot = (await session.execute(select(UserTrafficAnomaly))).scalar_one()

    assert result.created_snapshots == 1
    assert snapshot.last_lifetime_used_traffic_bytes == 100
    assert snapshot.last_traffic_delta_bytes == 0
    assert snapshot.is_suspicious is False


@pytest.mark.asyncio
async def test_next_iteration_updates_delta_and_marks_suspicious(session_maker):
    await add_user(session_maker)
    rwms = FakeRwmsClient(
        [FakeRwmsUser(username="user-1", lifetime_used_traffic_bytes=100)]
    )
    monitor = TrafficMonitor(session_maker, rwms, anomaly_threshold_bytes=200)
    await monitor.run_once()

    rwms.users = [FakeRwmsUser(username="user-1", lifetime_used_traffic_bytes=300)]
    result = await monitor.run_once()

    async with session_maker() as session:
        snapshot = (await session.execute(select(UserTrafficAnomaly))).scalar_one()

    assert result.updated_snapshots == 1
    assert result.suspicious_users == 1
    assert snapshot.last_lifetime_used_traffic_bytes == 300
    assert snapshot.last_traffic_delta_bytes == 200
    assert snapshot.is_suspicious is True
    assert snapshot.detected_at is not None


@pytest.mark.asyncio
async def test_auto_block_disables_anomalous_user_once(session_maker):
    await add_user(session_maker)
    rwms = FakeRwmsClient(
        [FakeRwmsUser(username="user-1", lifetime_used_traffic_bytes=100)]
    )
    monitor = TrafficMonitor(
        session_maker,
        rwms,
        anomaly_threshold_bytes=200,
        auto_block_enabled=True,
        auto_block_threshold_bytes=200,
    )
    await monitor.run_once()

    rwms.users = [FakeRwmsUser(username="user-1", lifetime_used_traffic_bytes=300)]
    result = await monitor.run_once()

    async with session_maker() as session:
        snapshot = (await session.execute(select(UserTrafficAnomaly))).scalar_one()

    assert result.blocked_users == 1
    assert rwms.disabled == ["user-1"]
    assert snapshot.is_blocked is True


@pytest.mark.asyncio
async def test_suspicious_user_sends_admin_notification(session_maker):
    await add_user(session_maker, user_id=7, username="user-7")
    rwms = FakeRwmsClient(
        [FakeRwmsUser(username="user-7", lifetime_used_traffic_bytes=100)]
    )
    notifier = FakeNotifier()
    monitor = TrafficMonitor(
        session_maker,
        rwms,
        anomaly_threshold_bytes=200,
        notifier=notifier,
    )
    await monitor.run_once()

    rwms.users = [FakeRwmsUser(username="user-7", lifetime_used_traffic_bytes=350)]
    result = await monitor.run_once()

    assert result.notifications_sent == 1
    assert len(notifier.anomalies) == 1
    assert notifier.anomalies[0].username == "user-7"
    assert notifier.anomalies[0].telegram_id == 7
    assert notifier.anomalies[0].delta_bytes == 250


@pytest.mark.asyncio
async def test_unknown_bot_user_is_skipped(session_maker):
    rwms = FakeRwmsClient(
        [FakeRwmsUser(username="unknown", lifetime_used_traffic_bytes=300)]
    )
    monitor = TrafficMonitor(session_maker, rwms, anomaly_threshold_bytes=200)

    result = await monitor.run_once()

    assert result.total_rwms_users == 1
    assert result.matched_users == 0
    async with session_maker() as session:
        snapshots = (await session.execute(select(UserTrafficAnomaly))).scalars().all()
    assert snapshots == []
