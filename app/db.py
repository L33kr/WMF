import sqlite3
from pathlib import Path
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = '''
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  category TEXT,
  dirty INTEGER NOT NULL DEFAULT 1,
  next_refresh REAL NOT NULL DEFAULT 0,
  updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_items_refresh ON items(dirty,next_refresh);

CREATE TABLE IF NOT EXISTS market(
  item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  min_price REAL,
  median REAL,
  avg_price REAL,
  p25 REAL,
  p75 REAL,
  buy_max REAL,
  sellers INTEGER NOT NULL DEFAULT 0,
  buyers INTEGER NOT NULL DEFAULT 0,
  seller_qty INTEGER NOT NULL DEFAULT 0,
  buyer_qty INTEGER NOT NULL DEFAULT 0,
  liquidity REAL,
  score REAL,
  updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_market_score ON market(score DESC);
CREATE INDEX IF NOT EXISTS idx_market_median ON market(median);

CREATE TABLE IF NOT EXISTS price_history(
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ts REAL NOT NULL,
  min_price REAL,
  median REAL,
  buy_max REAL,
  liquidity REAL,
  score REAL
);
CREATE INDEX IF NOT EXISTS idx_history_item_ts ON price_history(item_id,ts DESC);
'''

def init_db():
    p = Path(DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p) as c:
        c.executescript(SCHEMA)
        c.commit()

@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()
