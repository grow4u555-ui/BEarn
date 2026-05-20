#!/usr/bin/env python3
"""
BEarn Database Layer
SQLite-backed real-time earnings tracking with batch update support.
"""

import sqlite3
import time
import os
import json
from datetime import datetime, timedelta
from threading import Lock, Thread
from queue import Queue

DB_PATH = os.getenv("BEARN_DB_PATH", "data/bearn.db")
BATCH_INTERVAL = int(os.getenv("BEARN_BATCH_INTERVAL", "10"))  # seconds

# Thread-safe batch queue
_batch_queue = Queue()
_batch_lock = Lock()
_db_local = threading.local()

# ── Schema ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    UNIQUE NOT NULL,
    token_hash  TEXT    NOT NULL,
    earning_rate REAL   NOT NULL DEFAULT 0.001,   -- $ per MB
    referral_code TEXT  UNIQUE,
    referred_by  INTEGER REFERENCES users(id),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS proxy_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    method      TEXT,
    host        TEXT,
    path        TEXT,
    status_code INTEGER,
    bytes_sent  INTEGER DEFAULT 0,
    bytes_recv  INTEGER DEFAULT 0,
    duration_ms INTEGER,
    ip_address  TEXT,
    user_agent  TEXT
);

CREATE TABLE IF NOT EXISTS earnings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount      REAL    NOT NULL,
    rate_used   REAL    NOT NULL,
    source      TEXT    DEFAULT 'proxy',        -- 'proxy' | 'referral' | 'bonus'
    ref_id      INTEGER,                        -- optional link to proxy_logs.id
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount      REAL    NOT NULL,
    method      TEXT    DEFAULT 'stripe',
    status      TEXT    DEFAULT 'pending',       -- pending | completed | failed
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_proxy_logs_user_id ON proxy_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_proxy_logs_timestamp ON proxy_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_earnings_user_id ON earnings(user_id);
CREATE INDEX IF NOT EXISTS idx_earnings_created ON earnings(created_at);
CREATE INDEX IF NOT EXISTS idx_payouts_user_id ON payouts(user_id);
CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status);
"""

# ── Core Helpers ────────────────────────────────────────────────────────

def get_connection():
    """Get a thread-local SQLite connection."""
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db_local.conn = sqlite3.connect(DB_PATH)
        _db_local.conn.row_factory = sqlite3.Row
        _db_local.conn.execute("PRAGMA journal_mode=WAL;")
        _db_local.conn.execute("PRAGMA busy_timeout=5000;")
    return _db_local.conn

def init_db():
    """Create tables on first run."""
    conn = get_connection()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    print(f"[DB] Database initialized at {DB_PATH}")

def close_db():
    """Clean up thread-local connection."""
    if hasattr(_db_local, "conn") and _db_local.conn:
        _db_local.conn.close()
        _db_local.conn = None

# ── User Operations ─────────────────────────────────────────────────────

def register_user(username, token_hash, earning_rate=0.001, referral_code=None, referred_by=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO users (username, token_hash, earning_rate, referral_code, referred_by)
               VALUES (?, ?, ?, ?, ?)""",
            (username, token_hash, earning_rate, referral_code, referred_by)
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None

def get_user_by_token(token_hash):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE token_hash = ? AND is_active = 1", (token_hash,)
    ).fetchone()
    return dict(row) if row else None

def get_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

def update_earning_rate(user_id, new_rate):
    conn = get_connection()
    conn.execute("UPDATE users SET earning_rate = ? WHERE id = ?", (new_rate, user_id))
    conn.commit()

# ── Proxy Log ───────────────────────────────────────────────────────────

def insert_proxy_log(user_id, method, host, path, status_code, bytes_sent, bytes_recv, duration_ms, ip, ua):
    """Insert a single proxy log (direct, no batching)."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO proxy_logs (user_id, method, host, path, status_code,
                                   bytes_sent, bytes_recv, duration_ms, ip_address, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, method, host, path, status_code, bytes_sent, bytes_recv, duration_ms, ip, ua)
    )
    conn.commit()

def batch_insert_proxy_logs(logs):
    """Batch insert many proxy log rows at once."""
    conn = get_connection()
    conn.executemany(
        """INSERT INTO proxy_logs (user_id, method, host, path, status_code,
                                   bytes_sent, bytes_recv, duration_ms, ip_address, user_agent)
           VALUES (:user_id, :method, :host, :path, :status_code,
                   :bytes_sent, :bytes_recv, :duration_ms, :ip_address, :user_agent)""",
        logs
    )
    conn.commit()

# ── Earnings ────────────────────────────────────────────────────────────

def calculate_earnings(bytes_sent, bytes_recv, rate_per_mb):
    """Convert bytes to MB and multiply by rate."""
    total_mb = (bytes_sent + bytes_recv) / (1024 * 1024)
    return round(total_mb * rate_per_mb, 6)

def insert_earning(user_id, amount, rate_used, source="proxy", ref_id=None):
    conn = get_connection()
    conn.execute(
        """INSERT INTO earnings (user_id, amount, rate_used, source, ref_id)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, amount, rate_used, source, ref_id)
    )
    conn.commit()

def batch_insert_earnings(earnings_list):
    conn = get_connection()
    conn.executemany(
        """INSERT INTO earnings (user_id, amount, rate_used, source, ref_id)
           VALUES (:user_id, :amount, :rate_used, :source, :ref_id)""",
        earnings_list
    )
    conn.commit()

def get_user_balance(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS balance FROM earnings WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return row["balance"]

def get_user_earnings_history(user_id, limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM earnings WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]

# ── Payouts ─────────────────────────────────────────────────────────────

def request_payout(user_id, amount, method="stripe"):
    if amount < 5.0:
        return False, "Minimum withdrawal is $5.00"
    balance = get_user_balance(user_id)
    if balance < amount:
        return False, f"Insufficient balance (${balance:.2f})"
    conn = get_connection()
    conn.execute(
        "INSERT INTO payouts (user_id, amount, method) VALUES (?, ?, ?)",
        (user_id, amount, method)
    )
    conn.commit()
    return True, "Payout requested"

def get_payout_history(user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM payouts WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]

# ── Analytics ───────────────────────────────────────────────────────────

def get_traffic_summary(user_id, since=None):
    if since is None:
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) AS requests,
                  COALESCE(SUM(bytes_sent + bytes_recv), 0) AS total_bytes,
                  COALESCE(AVG(duration_ms), 0) AS avg_duration
           FROM proxy_logs
           WHERE user_id = ? AND timestamp >= ?""",
        (user_id, since)
    ).fetchone()
    return dict(row)

def get_daily_earnings(user_id, days=7):
    conn = get_connection()
    rows = conn.execute(
        """SELECT DATE(created_at) AS day, SUM(amount) AS total
           FROM earnings
           WHERE user_id = ? AND created_at >= datetime('now', ?)
           GROUP BY day ORDER BY day""",
        (user_id, f"-{days} days")
    ).fetchall()
    return [dict(r) for r in rows]

# ── Batch Worker ────────────────────────────────────────────────────────

def batch_worker():
    """Background thread that flushes the queue every BATCH_INTERVAL seconds."""
    buffer = []
    last_flush = time.time()

    while True:
        try:
            item = _batch_queue.get(timeout=1)
            buffer.append(item)
        except:  # timeout
            pass

        elapsed = time.time() - last_flush
        if buffer and elapsed >= BATCH_INTERVAL:
            try:
                logs = [e["log"] for e in buffer if e["type"] == "log"]
                earnings = [e["earn"] for e in buffer if e["type"] == "earn"]

                if logs:
                    batch_insert_proxy_logs(logs)
                if earnings:
                    batch_insert_earnings(earnings)

                print(f"[Batch] Flushed {len(logs)} logs, {len(earnings)} earnings")
                buffer.clear()
                last_flush = time.time()
            except Exception as ex:
                print(f"[Batch] Error: {ex}")

def enqueue_log(user_id, method, host, path, status_code, bytes_sent, bytes_recv, duration_ms, ip, ua):
    _batch_queue.put({
        "type": "log",
        "log": {
            "user_id": user_id, "method": method, "host": host, "path": path,
            "status_code": status_code, "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv, "duration_ms": duration_ms,
            "ip_address": ip, "user_agent": ua
        }
    })

def enqueue_earn(user_id, amount, rate_used, source="proxy", ref_id=None):
    _batch_queue.put({
        "type": "earn",
        "earn": {
            "user_id": user_id, "amount": amount, "rate_used": rate_used,
            "source": source, "ref_id": ref_id
        }
    })

def start_batch_worker():
    t = Thread(target=batch_worker, daemon=True)
    t.start()
    print(f"[Batch] Worker started (flush every {BATCH_INTERVAL}s)")
