"""Local Gemini request counts grouped by Google's Pacific-time quota day."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3

from PyQt6.QtCore import QTimeZone, Qt

from app_logging import log_throttled


PACIFIC_TIME = QTimeZone(b"America/Los_Angeles")
USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "gemini_usage.sqlite3"


def quota_day(moment):
    return moment.toTimeZone(PACIFIC_TIME).date()


def record_attempt(api_key, model, started_at, status, failed):
    day = quota_day(started_at).toString(Qt.DateFormat.ISODate)
    key_hash = sha256(api_key.encode("utf-8")).hexdigest()
    status = status if isinstance(status, int) else 0
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(USAGE_PATH, timeout=.25)) as database, database:
            database.execute("""CREATE TABLE IF NOT EXISTS gemini_usage (
                day TEXT, key_hash TEXT, model TEXT, status INTEGER, failed INTEGER, calls INTEGER,
                PRIMARY KEY (day, key_hash, model, status, failed)
            )""")
            database.execute("""
                INSERT INTO gemini_usage VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT (day, key_hash, model, status, failed) DO UPDATE SET calls = calls + 1
            """, (day, key_hash, model, status, failed))
    except (OSError, sqlite3.Error) as error:
        log_throttled("gemini.usage_write_failed", "Gemini 호출량 기록 실패",
                      category="대화·AI", level="WARNING", interval=60, error=str(error))


def daily_usage(api_key, day):
    """Map models to (attempts, estimated quota usage, failures, HTTP 429s)."""
    if not api_key:
        return {}
    try:
        if not USAGE_PATH.exists():
            return {}
        key_hash = sha256(api_key.encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(USAGE_PATH.as_uri() + "?mode=ro", uri=True, timeout=.1)) as database:
            # Google documents that 400 and 500 errors also count against the quota.
            rows = database.execute("""
                SELECT model, SUM(calls),
                    SUM(CASE WHEN status BETWEEN 200 AND 299 OR status IN (400, 500) THEN calls ELSE 0 END),
                    SUM(CASE WHEN failed THEN calls ELSE 0 END),
                    SUM(CASE WHEN status = 429 THEN calls ELSE 0 END)
                FROM gemini_usage WHERE day = ? AND key_hash = ? GROUP BY model
            """, (day.toString(Qt.DateFormat.ISODate), key_hash))
            return {model: (attempts, estimated, failed, limited)
                    for model, attempts, estimated, failed, limited in rows}
    except (OSError, sqlite3.Error) as error:
        log_throttled("gemini.usage_read_failed", "Gemini 호출량을 불러오지 못했습니다.",
                      category="대화·AI", level="WARNING", interval=60, error=str(error))
        return None
