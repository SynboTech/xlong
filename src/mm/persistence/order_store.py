from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from typing import Iterable, List, Protocol
from urllib.parse import urlparse

from mm.oms.order import OrderRecord


class OrderStore(Protocol):
    def load(self) -> List[OrderRecord]:
        ...

    def save(self, orders: Iterable[OrderRecord]) -> None:
        ...

    def save_order(self, order: OrderRecord) -> None:
        ...


class JsonOrderStore:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def load(self) -> List[OrderRecord]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [OrderRecord.from_dict(row) for row in data.get("orders", [])]

    def save(self, orders: Iterable[OrderRecord]) -> None:
        parent = os.path.dirname(self.path) or "."
        payload = {"orders": [order.to_dict() for order in orders]}
        fd, tmp_path = tempfile.mkstemp(prefix=".orders-", suffix=".json", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
                fh.write("\n")
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def save_order(self, order: OrderRecord) -> None:
        orders = {existing.client_order_id: existing for existing in self.load()}
        orders[order.client_order_id] = order
        self.save(orders.values())


class SQLiteOrderStore:
    def __init__(self, path: str) -> None:
        self.path = _sqlite_path(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._ensure_schema()

    def load(self) -> List[OrderRecord]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT payload_json FROM orders ORDER BY created_at_ms ASC, client_order_id ASC"
            ).fetchall()
        return [OrderRecord.from_dict(json.loads(row["payload_json"])) for row in rows]

    def save(self, orders: Iterable[OrderRecord]) -> None:
        rows = [order.to_dict() for order in orders]
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN")
            self._upsert_rows(conn, rows)
            if rows:
                conn.execute("CREATE TEMP TABLE IF NOT EXISTS active_order_ids(client_order_id TEXT PRIMARY KEY)")
                conn.execute("DELETE FROM active_order_ids")
                conn.executemany(
                    "INSERT INTO active_order_ids(client_order_id) VALUES (?)",
                    [(row["client_order_id"],) for row in rows],
                )
                conn.execute(
                    "DELETE FROM orders WHERE client_order_id NOT IN (SELECT client_order_id FROM active_order_ids)"
                )
            else:
                conn.execute("DELETE FROM orders")
            conn.commit()

    def save_order(self, order: OrderRecord) -> None:
        with sqlite3.connect(self.path) as conn:
            self._upsert_rows(conn, [order.to_dict()])
            conn.commit()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price TEXT,
                    size TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    level INTEGER,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    filled_size TEXT NOT NULL,
                    avg_fill_price TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    last_message TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy_status ON orders(strategy, status)")

    @staticmethod
    def _row_values(row: dict) -> tuple:
        return (
            row["client_order_id"],
            row["symbol"],
            row["side"],
            row.get("price"),
            row["size"],
            row["order_type"],
            row["strategy"],
            row.get("level"),
            row["status"],
            row.get("exchange_order_id"),
            row.get("filled_size", "0"),
            row.get("avg_fill_price"),
            int(row.get("created_at_ms", 0)),
            int(row.get("updated_at_ms", 0)),
            row.get("last_message", ""),
            json.dumps(row, sort_keys=True, separators=(",", ":")),
        )

    def _upsert_rows(self, conn: sqlite3.Connection, rows: List[dict]) -> None:
        conn.executemany(
            """
            INSERT INTO orders (
                client_order_id, symbol, side, price, size, order_type, strategy, level,
                status, exchange_order_id, filled_size, avg_fill_price, created_at_ms,
                updated_at_ms, last_message, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_order_id) DO UPDATE SET
                symbol=excluded.symbol,
                side=excluded.side,
                price=excluded.price,
                size=excluded.size,
                order_type=excluded.order_type,
                strategy=excluded.strategy,
                level=excluded.level,
                status=excluded.status,
                exchange_order_id=excluded.exchange_order_id,
                filled_size=excluded.filled_size,
                avg_fill_price=excluded.avg_fill_price,
                created_at_ms=excluded.created_at_ms,
                updated_at_ms=excluded.updated_at_ms,
                last_message=excluded.last_message,
                payload_json=excluded.payload_json
            """,
            [self._row_values(row) for row in rows],
        )


class PostgresOrderStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._driver = self._load_driver()
        self._ensure_schema()

    def load(self) -> List[OrderRecord]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT payload_json FROM orders ORDER BY created_at_ms ASC, client_order_id ASC")
            rows = cur.fetchall()
            return [OrderRecord.from_dict(self._payload(row[0])) for row in rows]
        finally:
            conn.close()

    def save(self, orders: Iterable[OrderRecord]) -> None:
        rows = [order.to_dict() for order in orders]
        conn = self._connect()
        try:
            cur = conn.cursor()
            self._upsert_rows(cur, rows)
            if rows:
                cur.execute(
                    "DELETE FROM orders WHERE client_order_id <> ALL(%s)",
                    ([row["client_order_id"] for row in rows],),
                )
            else:
                cur.execute("DELETE FROM orders")
            conn.commit()
        finally:
            conn.close()

    def save_order(self, order: OrderRecord) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            self._upsert_rows(cur, [order.to_dict()])
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price TEXT,
                    size TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    level INTEGER,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    filled_size TEXT NOT NULL,
                    avg_fill_price TEXT,
                    created_at_ms BIGINT NOT NULL,
                    updated_at_ms BIGINT NOT NULL,
                    last_message TEXT NOT NULL,
                    payload_json JSONB NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy_status ON orders(strategy, status)")
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        if self._driver[0] == "psycopg":
            return self._driver[1].connect(self.dsn)
        return self._driver[1].connect(self.dsn)

    @staticmethod
    def _payload(value):
        if isinstance(value, str):
            return json.loads(value)
        return dict(value)

    @staticmethod
    def _row_values(row: dict) -> tuple:
        return (
            row["client_order_id"],
            row["symbol"],
            row["side"],
            row.get("price"),
            row["size"],
            row["order_type"],
            row["strategy"],
            row.get("level"),
            row["status"],
            row.get("exchange_order_id"),
            row.get("filled_size", "0"),
            row.get("avg_fill_price"),
            int(row.get("created_at_ms", 0)),
            int(row.get("updated_at_ms", 0)),
            row.get("last_message", ""),
            json.dumps(row, sort_keys=True, separators=(",", ":")),
        )

    def _upsert_rows(self, cur, rows: List[dict]) -> None:
        cur.executemany(
            """
            INSERT INTO orders (
                client_order_id, symbol, side, price, size, order_type, strategy, level,
                status, exchange_order_id, filled_size, avg_fill_price, created_at_ms,
                updated_at_ms, last_message, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(client_order_id) DO UPDATE SET
                symbol=excluded.symbol,
                side=excluded.side,
                price=excluded.price,
                size=excluded.size,
                order_type=excluded.order_type,
                strategy=excluded.strategy,
                level=excluded.level,
                status=excluded.status,
                exchange_order_id=excluded.exchange_order_id,
                filled_size=excluded.filled_size,
                avg_fill_price=excluded.avg_fill_price,
                created_at_ms=excluded.created_at_ms,
                updated_at_ms=excluded.updated_at_ms,
                last_message=excluded.last_message,
                payload_json=excluded.payload_json
            """,
            [self._row_values(row) for row in rows],
        )

    @staticmethod
    def _load_driver():
        try:
            import psycopg  # type: ignore

            return ("psycopg", psycopg)
        except ImportError:
            try:
                import psycopg2  # type: ignore

                return ("psycopg2", psycopg2)
            except ImportError as exc:
                raise RuntimeError(
                    "Postgres order store requires psycopg or psycopg2 to be installed"
                ) from exc


def build_order_store(path: str) -> OrderStore:
    lower = path.lower()
    if lower.startswith("postgres://") or lower.startswith("postgresql://"):
        return PostgresOrderStore(path)
    if lower.startswith("sqlite://") or lower.endswith(".db") or lower.endswith(".sqlite") or lower.endswith(".sqlite3"):
        return SQLiteOrderStore(path)
    return JsonOrderStore(path)


def _sqlite_path(path: str) -> str:
    if not path.startswith("sqlite://"):
        return path
    parsed = urlparse(path)
    if parsed.netloc and parsed.path:
        return os.path.join(parsed.netloc, parsed.path.lstrip(os.sep))
    return parsed.path or parsed.netloc
