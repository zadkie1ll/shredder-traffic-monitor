# shredder-traffik-monitor

Worker for monitoring Remnawave user traffic deltas.

The service reads users from Remnawave, matches them with `common.models.db.User`
by username, and keeps one compact row per user in `user_traffic_anomalies`.
By default it checks traffic every 10 minutes, marks a user suspicious at
50 GiB delta, and can auto-block at 100 GiB delta when auto-blocking is enabled.
Users whose `expire_at` is one year or more in the future are skipped, so
long-term/lifetime subscriptions are not monitored or auto-blocked.

Stored values:

- `last_lifetime_used_traffic_bytes` - previous Remnawave lifetime counter.
- `last_traffic_delta_bytes` - delta between the previous and current counter.
- `is_suspicious` - true when delta reaches the configured threshold.
- `is_blocked` - true when auto-blocking was enabled and RWMS disable succeeded.

## Run

```bash
cp .env.example .env
docker compose up -d --build
```

By default auto-blocking is disabled. Enable it explicitly:

```env
TRAFFIC_MONITOR_AUTO_BLOCK_ENABLED=true
```

Telegram alerts can be sent through `shredder-vpn-bot`. Put the target admin
chat id in this service `.env` and reuse the VPN bot token:

```env
MI_VPN_BOT_TOKEN=123456:token-from-shredder-vpn-bot
TRAFFIC_MONITOR_TELEGRAM_NOTIFY_CHAT_ID=123456789
```

You can also set `TRAFFIC_MONITOR_TELEGRAM_NOTIFY_CHAT_IDS` as a comma-separated
list, or override the token with `TRAFFIC_MONITOR_TELEGRAM_BOT_TOKEN`.
Each anomaly alert includes an admin-only button that disables the user in
RWMS. The `block_user:` callback is handled by `shredder-vpn-bot`, which already
owns Telegram polling for the shared bot token.

Schema is described and migrated in the `common` submodule. For a first
bootstrap run you can also set `TRAFFIC_MONITOR_CREATE_SCHEMA=true`.
