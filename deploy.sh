#!/usr/bin/env bash
set -euo pipefail
APP=/opt/wfm-trader
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
if ! id wfm >/dev/null 2>&1; then sudo useradd --system --create-home --home "$APP" --shell /usr/sbin/nologin wfm; fi
sudo mkdir -p "$APP/data"
sudo cp -r ./* "$APP/"
sudo chown -R wfm:wfm "$APP"
cd "$APP"
if [ ! -f .env ]; then sudo -u wfm cp .env.example .env; fi
sudo -u wfm python3 -m venv .venv
sudo -u wfm .venv/bin/pip install --upgrade pip
sudo -u wfm .venv/bin/pip install -r requirements.txt
sudo cp systemd/wfm-trader.service /etc/systemd/system/wfm-trader.service
sudo cp nginx/wfm-trader.conf /etc/nginx/sites-available/wfm-trader.conf
sudo ln -sf /etc/nginx/sites-available/wfm-trader.conf /etc/nginx/sites-enabled/wfm-trader.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload
sudo systemctl enable --now wfm-trader
sudo nginx -t
sudo systemctl reload nginx
echo "Open http://SERVER_IP/"
