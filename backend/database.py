"""SQLite persistence for guardrails, orders, and audit logs."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import AuditLogEntry, GuardrailsConfig, OrderResponse, QuotedProduct

DB_PATH = Path(__file__).resolve().parent / "valio_gateway.db"
DEFAULT_GUARDRAILS = GuardrailsConfig(max_autonomous_spend_eur=500.0, forbidden_allergens=["lactose"], allow_substitutions=True)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create tables and seed the default guardrails exactly once."""
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS guardrails (id INTEGER PRIMARY KEY CHECK (id = 1), max_autonomous_spend_eur REAL NOT NULL, forbidden_allergens TEXT NOT NULL, allow_substitutions INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (order_id TEXT PRIMARY KEY, status TEXT NOT NULL, total_eur REAL NOT NULL, blocked_reasons_json TEXT NOT NULL, items_json TEXT NOT NULL, quote_token TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, reasoning TEXT NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO guardrails VALUES (1, 500.0, ?, 1)", (json.dumps(["lactose"]),))


def get_guardrails() -> GuardrailsConfig:
    with _connect() as db:
        row = db.execute("SELECT * FROM guardrails WHERE id = 1").fetchone()
    return GuardrailsConfig(max_autonomous_spend_eur=row["max_autonomous_spend_eur"], forbidden_allergens=json.loads(row["forbidden_allergens"]), allow_substitutions=bool(row["allow_substitutions"]))


def save_guardrails(config: GuardrailsConfig) -> GuardrailsConfig:
    with _connect() as db:
        db.execute("UPDATE guardrails SET max_autonomous_spend_eur=?, forbidden_allergens=?, allow_substitutions=? WHERE id=1", (config.max_autonomous_spend_eur, json.dumps(config.forbidden_allergens), int(config.allow_substitutions)))
    return config


def reset_demo() -> None:
    """Clear demo orders and audit logs and restore the default guardrails."""
    with _connect() as db:
        db.execute("DELETE FROM audit_logs")
        db.execute("DELETE FROM orders")
        db.execute(
            "UPDATE guardrails SET max_autonomous_spend_eur=?, forbidden_allergens=?, allow_substitutions=? WHERE id=1",
            (DEFAULT_GUARDRAILS.max_autonomous_spend_eur, json.dumps(DEFAULT_GUARDRAILS.forbidden_allergens), int(DEFAULT_GUARDRAILS.allow_substitutions)),
        )


def save_order(order: OrderResponse, quote_token: str) -> None:
    with _connect() as db:
        if not quote_token:
            existing = db.execute("SELECT quote_token FROM orders WHERE order_id=?", (order.order_id,)).fetchone()
            quote_token = existing["quote_token"] if existing else ""
        db.execute("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", (order.order_id, order.status, order.total_eur, json.dumps(order.blocked_reasons), json.dumps([item.model_dump() for item in order.items]), quote_token, datetime.now(timezone.utc).isoformat()))
        db.execute("DELETE FROM audit_logs WHERE order_id=?", (order.order_id,))
        for entry in order.audit_trail:
            db.execute("INSERT INTO audit_logs (order_id,timestamp,actor,action,reasoning) VALUES (?,?,?,?,?)", (order.order_id, entry.timestamp, entry.actor, entry.action, entry.reasoning))


def _row_to_order(row: sqlite3.Row, logs: list[sqlite3.Row]) -> OrderResponse:
    return OrderResponse(order_id=row["order_id"], status=row["status"], total_eur=row["total_eur"], blocked_reasons=json.loads(row["blocked_reasons_json"]), items=[QuotedProduct(**item) for item in json.loads(row["items_json"])], audit_trail=[AuditLogEntry(timestamp=log["timestamp"], actor=log["actor"], action=log["action"], reasoning=log["reasoning"]) for log in logs])


def get_order(order_id: str) -> OrderResponse | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            return None
        logs = db.execute("SELECT * FROM audit_logs WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
    return _row_to_order(row, logs)


def list_orders() -> list[OrderResponse]:
    with _connect() as db:
        rows = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        return [_row_to_order(row, db.execute("SELECT * FROM audit_logs WHERE order_id=? ORDER BY id", (row["order_id"],)).fetchall()) for row in rows]
