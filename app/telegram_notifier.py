from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib import request
from urllib.error import HTTPError, URLError

BLOCK_CALLBACK_PREFIX = "block_user:"


@dataclass(frozen=True)
class TrafficAnomalyNotification:
    username: str
    user_id: int
    telegram_id: int
    previous_traffic_bytes: int
    current_traffic_bytes: int
    delta_bytes: int
    average_speed_mbps: float
    speed_threshold_mbps: int
    reason: str
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
                if await self.send_message(
                    chat_id=chat_id,
                    text=text,
                    user_id=None if anomaly.blocked else anomaly.user_id,
                ):
                    sent += 1

        return sent

    async def send_message(
        self,
        chat_id: int,
        text: str,
        user_id: int | None = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._send_message_sync,
            chat_id,
            text,
            user_id,
        )

    def _send_message_sync(
        self,
        chat_id: int,
        text: str,
        user_id: int | None,
    ) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if user_id is not None:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Заблокировать пользователя",
                            "callback_data": f"{BLOCK_CALLBACK_PREFIX}{user_id}",
                        }
                    ]
                ]
            }

        return self._telegram_request("sendMessage", payload) is not None

    def _telegram_request(
        self,
        method: str,
        payload: dict,
        timeout_seconds: int | None = None,
    ):
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        encoded_payload = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(
                req,
                timeout=timeout_seconds or self._timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
                if 200 <= response.status < 300 and body.get("ok"):
                    return body.get("result")
                return None
        except HTTPError as exc:
            self._log.warning(
                "telegram %s failed: HTTP %s",
                method,
                exc.code,
            )
            return None
        except URLError:
            self._log.exception("telegram %s failed", method)
            return None

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
                f"Average speed: <b>{anomaly.average_speed_mbps:.2f} Mbps</b>",
                f"Speed threshold: {anomaly.speed_threshold_mbps} Mbps",
                f"Delta: <b>{_format_bytes(anomaly.delta_bytes)}</b>",
                f"Previous: {_format_bytes(anomaly.previous_traffic_bytes)}",
                f"Current: {_format_bytes(anomaly.current_traffic_bytes)}",
                f"Reason: <code>{escape(anomaly.reason)}</code>",
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
