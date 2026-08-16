import os

API_BASE = os.getenv('WFM_API_BASE', 'https://api.warframe.market/v2')
WS_URL = os.getenv('WFM_WS_URL', 'wss://warframe.market/socket?platform=pc')
PLATFORM = os.getenv('WFM_PLATFORM', 'pc')
CROSSPLAY = os.getenv('WFM_CROSSPLAY', 'true').lower() == 'true'
DB_PATH = os.getenv('DB_PATH', './data/wfm.db')
RECENT_SYNC_SECONDS = int(os.getenv('RECENT_SYNC_SECONDS', '300'))
REFRESH_BATCH = int(os.getenv('REFRESH_BATCH', '12'))
REFRESH_INTERVAL_SECONDS = int(os.getenv('REFRESH_INTERVAL_SECONDS', '900'))
HISTORY_RETENTION_DAYS = int(os.getenv('HISTORY_RETENTION_DAYS', '45'))
WFM_REQUEST_DELAY = float(os.getenv('WFM_REQUEST_DELAY', '0.2'))
HOST = os.getenv('HOST', '127.0.0.1')
PORT = int(os.getenv('PORT', '8000'))
