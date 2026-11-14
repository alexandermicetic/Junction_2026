"""SQLite persistence for guardrails, orders, audit logs, and inventory rules."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import AuditLogEntry, GuardrailsConfig, InventoryRule, OrderResponse, QuotedProduct

DB_PATH = Path(__file__).resolve().parent / "valio_gateway.db"
DEFAULT_GUARDRAILS = GuardrailsConfig(max_autonomous_spend_eur=500.0, forbidden_allergens=["lactose"], allow_substitutions=True)
DEFAULT_INVENTORY = [
    {"sku": "460825", "name": "Oatly Oat Drink Organic 1L", "product_query": "Oatly Oat Drink Organic 1L", "unit": "PCS", "current_stock": 7, "min_threshold": 8, "reorder_quantity": 24, "auto_reorder_enabled": True, "buyer_id": "BUYER-TEST-001"},
    {"sku": "464201", "name": "Valio lactose-free semi-skimmed milk 1L", "product_query": "Valio semi skimmed milk 1 l lactose free UHT", "unit": "PCS", "current_stock": 4, "min_threshold": 5, "reorder_quantity": 12, "auto_reorder_enabled": True, "buyer_id": "BUYER-TEST-001"},
    {"sku": "463359", "name": "Valio low-fat milk 1L", "product_query": "Valio semi skimmed milk 1 l", "unit": "PCS", "current_stock": 16, "min_threshold": 8, "reorder_quantity": 24, "auto_reorder_enabled": True, "buyer_id": "BUYER-TEST-001"},
]


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
        CREATE TABLE IF NOT EXISTS inventory_rules (sku TEXT PRIMARY KEY, name TEXT NOT NULL, product_query TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'PCS', current_stock INTEGER NOT NULL CHECK (current_stock >= 0), min_threshold INTEGER NOT NULL CHECK (min_threshold >= 0), reorder_quantity INTEGER NOT NULL CHECK (reorder_quantity > 0), auto_reorder_enabled INTEGER NOT NULL DEFAULT 1, buyer_id TEXT NOT NULL DEFAULT 'BUYER-TEST-001');
        CREATE TABLE IF NOT EXISTS inventory_reorder_locks (sku TEXT PRIMARY KEY, locked_at TEXT NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO guardrails VALUES (1, 500.0, ?, 1)", (json.dumps(["lactose"]),))
        _seed_inventory(db)


def _seed_inventory(db: sqlite3.Connection) -> None:
    db.executemany(
        "INSERT OR IGNORE INTO inventory_rules (sku,name,product_query,unit,current_stock,min_threshold,reorder_quantity,auto_reorder_enabled,buyer_id) VALUES (:sku,:name,:product_query,:unit,:current_stock,:min_threshold,:reorder_quantity,:auto_reorder_enabled,:buyer_id)",
        [{**item, "auto_reorder_enabled": int(item["auto_reorder_enabled"])} for item in DEFAULT_INVENTORY],
    )


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
        db.execute("DELETE FROM inventory_reorder_locks")
        db.execute("DELETE FROM inventory_rules")
        _seed_inventory(db)
        db.execute(
            "UPDATE guardrails SET max_autonomous_spend_eur=?, forbidden_allergens=?, allow_substitutions=? WHERE id=1",
            (DEFAULT_GUARDRAILS.max_autonomous_spend_eur, json.dumps(DEFAULT_GUARDRAILS.forbidden_allergens), int(DEFAULT_GUARDRAILS.allow_substitutions)),
        )


def _row_to_inventory_rule(row: sqlite3.Row) -> InventoryRule:
    return InventoryRule(
        sku=row["sku"], name=row["name"], product_query=row["product_query"], unit=row["unit"],
        current_stock=row["current_stock"], min_threshold=row["min_threshold"],
        reorder_quantity=row["reorder_quantity"], auto_reorder_enabled=bool(row["auto_reorder_enabled"]),
        buyer_id=row["buyer_id"],
    )


def list_inventory_rules() -> list[InventoryRule]:
    with _connect() as db:
        rows = db.execute("SELECT * FROM inventory_rules ORDER BY name, sku").fetchall()
    return [_row_to_inventory_rule(row) for row in rows]


def get_inventory_rule(sku: str) -> InventoryRule | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM inventory_rules WHERE sku=?", (sku,)).fetchone()
    return _row_to_inventory_rule(row) if row else None


def update_inventory_rule(sku: str, updates: dict[str, Any]) -> InventoryRule | None:
    allowed = {"reorder_quantity", "min_threshold", "current_stock", "auto_reorder_enabled"}
    values = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if values:
        columns = ", ".join(f"{column}=?" for column in values)
        params = [int(value) if key == "auto_reorder_enabled" else value for key, value in values.items()]
        with _connect() as db:
            cursor = db.execute(f"UPDATE inventory_rules SET {columns} WHERE sku=?", [*params, sku])
            if cursor.rowcount == 0:
                return None
    return get_inventory_rule(sku)


def consume_inventory(sku: str, amount: int) -> InventoryRule | None:
    with _connect() as db:
        cursor = db.execute("UPDATE inventory_rules SET current_stock=MAX(0, current_stock-?) WHERE sku=?", (amount, sku))
        if cursor.rowcount == 0:
            return None
        row = db.execute("SELECT * FROM inventory_rules WHERE sku=?", (sku,)).fetchone()
    return _row_to_inventory_rule(row)


def acquire_reorder_lock(sku: str) -> bool:
    """Atomically reserve a SKU so concurrent scans cannot submit duplicates."""
    with _connect() as db:
        stale_before = datetime.now(timezone.utc).timestamp() - 900
        stale_iso = datetime.fromtimestamp(stale_before, timezone.utc).isoformat()
        db.execute("DELETE FROM inventory_reorder_locks WHERE locked_at < ?", (stale_iso,))
        cursor = db.execute("INSERT OR IGNORE INTO inventory_reorder_locks (sku,locked_at) VALUES (?,?)", (sku, datetime.now(timezone.utc).isoformat()))
        return cursor.rowcount == 1


def release_reorder_lock(sku: str) -> None:
    with _connect() as db:
        db.execute("DELETE FROM inventory_reorder_locks WHERE sku=?", (sku,))


def find_open_order_for_sku(sku: str) -> str | None:
    """Return the ID of a confirmed or approval-pending order containing this SKU."""
    with _connect() as db:
        rows = db.execute("SELECT order_id,items_json FROM orders WHERE status IN ('CONFIRMED','PENDING_APPROVAL') ORDER BY created_at DESC").fetchall()
    for row in rows:
        if any(str(item.get("sku")) == sku for item in json.loads(row["items_json"])):
            return row["order_id"]
    return None


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
