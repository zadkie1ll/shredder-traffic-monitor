from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib import request
from urllib.error import HTTPError, URLError


@dataclass(frozen=True)
class TrafficAnomalyNotification:
    username: str
    user_id: int
    telegram_id: int
    previous_traffic_bytes: int
    current_traffic_bytes: int
    delta_bytes: int
    anomaly_threshold_bytes: int
    should_block: bool
    blocked: bool = False
    detected_at: datetime | None = None


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_ids: list[int],
        timeout_seconds: int = 10,
    ) -> None:
        self._bot_token = bot_token
        self._chat_ids = chat_ids
        self._timeout_seconds = timeout_seconds
        self._log = logging.getLogger(self.__class__.__name__)

    async def notify_traffic_anomalies(
        self,
        anomalies: list[TrafficAnomalyNotification],
    ) -> int:
        if not anomalies or not self._chat_ids:
            return 0

        sent = 0
        for anomaly in anomalies:
            text = self._format_anomaly(anomaly)
            for chat_id in self._chat_ids:
                if await self.send_message(chat_id=chat_id, text=text):
                    sent += 1

        return sent

    async def send_message(self, chat_id: int, text: str) -> bool:
        return await asyncio.to_thread(self._send_message_sync, chat_id, text)

    def _send_message_sync(self, chat_id: int, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return 200 <= response.status < 300
        except HTTPError as exc:
            self._log.warning(
                "telegram sendMessage failed for chat %s: HTTP %s",
                chat_id,
                exc.code,
            )
            return False
        except URLError:
            self._log.exception("telegram sendMessage failed for chat %s", chat_id)
            return False

    def _format_anomaly(self, anomaly: TrafficAnomalyNotification) -> str:
        status = "blocked" if anomaly.blocked else "not blocked"
        if anomaly.should_block and not anomaly.blocked:
            status = "block requested, failed or pending"

        return "\n".join(
            [
                "<b>Traffic anomaly detected</b>",
                f"Bot: <b>shredder-vpn-bot</b>",
                f"Username: <code>{escape(anomaly.username)}</code>",
                f"User ID: <code>{anomaly.user_id}</code>",
                f"Telegram ID: <code>{anomaly.telegram_id}</code>",
                f"Delta: <b>{_format_bytes(anomaly.delta_bytes)}</b>",
                f"Threshold: {_format_bytes(anomaly.anomaly_threshold_bytes)}",
                f"Previous: {_format_bytes(anomaly.previous_traffic_bytes)}",
                f"Current: {_format_bytes(anomaly.current_traffic_bytes)}",
                f"Status: <b>{status}</b>",
            ]
        )


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    unit = units[0]
    for unit in units:
        if abs(number) < 1024 or unit == units[-1]:
            break
        number /= 1024

    if unit == "B":
        return f"{int(number)} {unit}"
    return f"{number:.2f} {unit}"
