# WFM Trader — 1 vCPU / 1 GB RAM / 15 GB NVMe

Lightweight FastAPI + SQLite + background collector for Warframe.Market.

## What it does

- Keeps the full catalog from `/v2/items`.
- Shows all catalog items in the dashboard, not just the latest 25.
- Uses `/v2/orders/recent` to discover active/changed items.
- Uses the documented realtime `newOrders` WebSocket to mark items dirty.
- Refreshes only a small batch of item orderbooks at a time.
- Stores current aggregates and a compact rolling price history in SQLite WAL.
- No PostgreSQL, Redis, Docker or multiple workers required.

The official WFM docs currently document `@wfm|cmd/subscribe/newOrders` and `@wfm|event/subscriptions/newOrder`; the app uses those routes. See: https://docs.warframe.market/docs/websockets/subscriptions/

## Install on Ubuntu 26.04

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
cd /opt
sudo git clone YOUR_GITHUB_REPO wfm-trader
cd wfm-trader
sudo chown -R $USER:$USER .
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Then create service user/data directory and install the included systemd/Nginx configs. `deploy.sh` automates the process.

## Notes for 1 GB RAM

- One Uvicorn worker only.
- SQLite instead of PostgreSQL.
- No Redis.
- Collector runs inside the same process.
- History retention defaults to 45 days.
- Refresh batch defaults to 12 items.

The first run may take time to populate market metrics because the server intentionally does not hammer every item endpoint at once. The catalog itself is complete immediately after the `/items` sync.
