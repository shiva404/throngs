"""SQLite-backed bank store for street simulation: persist balance per account (place)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from throngs.config import settings

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    p = Path(settings.street_bank_db)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            place_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'sale',
            created_at TEXT NOT NULL,
            FOREIGN KEY (place_id) REFERENCES accounts(place_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tx_place ON transactions(place_id);
    """)


def get_connection() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_db(conn)
    return conn


def ensure_account(place_id: str, name: str, initial_balance: float = 0.0) -> None:
    """Create or leave account as-is; use initial_balance only when creating."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT 1 FROM accounts WHERE place_id = ?", (place_id,)
        )
        if cur.fetchone() is None:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO accounts (place_id, name, balance, updated_at) VALUES (?, ?, ?, ?)",
                (place_id, name, round(initial_balance, 2), now),
            )
            conn.commit()
            logger.debug("Bank: created account %s %s with balance %.2f", place_id, name, initial_balance)
    finally:
        conn.close()


def record_sale(place_id: str, amount: float, account_name: str, description: str = "Customer sale") -> float:
    """Record a sale for the place: add transaction and increase balance. Returns new balance."""
    ensure_account(place_id, account_name, initial_balance=settings.street_initial_bank_balance)
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO transactions (place_id, amount, description, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (place_id, round(amount, 2), description, "sale", now),
        )
        conn.execute(
            "UPDATE accounts SET balance = balance + ?, updated_at = ? WHERE place_id = ?",
            (round(amount, 2), now, place_id),
        )
        conn.commit()
        cur = conn.execute("SELECT balance FROM accounts WHERE place_id = ?", (place_id,))
        row = cur.fetchone()
        balance = float(row["balance"]) if row else 0.0
        logger.info("Bank: recorded sale %.2f for %s — balance now %.2f", amount, place_id, balance)
        return balance
    finally:
        conn.close()


def get_balances() -> list[dict]:
    """Return all accounts with current balance for the street UI."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT place_id, name, balance, updated_at FROM accounts ORDER BY place_id"
        )
        return [
            {
                "place_id": row["place_id"],
                "name": row["name"],
                "balance": round(float(row["balance"]), 2),
                "updated_at": row["updated_at"],
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()
