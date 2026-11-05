"""Short atomic on-disk transactions; no DB lock spans a provider call."""

import asyncio
from contextlib import closing, contextmanager
import math
from pathlib import Path
import sqlite3
import time

from .tokenization import COUNTING_METHOD, LEGACY_METHOD

LIMIT = 50000
WINDOW_SECONDS = 60.0
SCHEMA_VERSION = 2
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS quota_clock (singleton INTEGER PRIMARY KEY CHECK(singleton=1), latest REAL NOT NULL)",
    f"""CREATE TABLE IF NOT EXISTS reservations (
        request_id TEXT PRIMARY KEY,
        tenant TEXT NOT NULL,
        reserved INTEGER NOT NULL CHECK(reserved > 0 AND reserved <= 50000),
        units INTEGER NOT NULL CHECK(units >= 0 AND units <= reserved),
        state TEXT NOT NULL CHECK(state IN ('active','settled')),
        created_at REAL NOT NULL,
        settled_at REAL,
        accounting_method TEXT NOT NULL CHECK(accounting_method IN ('{COUNTING_METHOD}','{LEGACY_METHOD}')),
        CHECK ((state='active' AND settled_at IS NULL) OR (state='settled' AND settled_at IS NOT NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS quota_tenant ON reservations(tenant)",
    "CREATE INDEX IF NOT EXISTS quota_expiry ON reservations(settled_at) WHERE state='settled'",
)


class StoreUnavailable(RuntimeError):
    pass


class QuotaStore:
    def __init__(self, path, clock=time.time, busy_timeout=5.0):
        if str(path) == ":memory:" or str(path).startswith("file:"):
            raise ValueError("An on-disk SQLite path is required")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.busy_timeout = busy_timeout
        try:
            with closing(self._connect()) as connection:
                if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                    raise StoreUnavailable("WAL mode unavailable")
            with self._transaction() as (connection, now):
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, SCHEMA_VERSION):
                    raise StoreUnavailable("Unsupported quota schema version")
                for statement in SCHEMA:
                    connection.execute(statement)
                if version == 1:
                    # Raw prompt/output were never stored, so do not invent a
                    # conversion. Keep legacy amounts as conservative holds.
                    connection.execute(f"ALTER TABLE reservations ADD COLUMN accounting_method TEXT NOT NULL DEFAULT '{LEGACY_METHOD}'")
                columns = {row[1] for row in connection.execute("PRAGMA table_info(reservations)")}
                if "accounting_method" not in columns:
                    raise StoreUnavailable("Unknown quota accounting schema")
                unknown = connection.execute("SELECT 1 FROM reservations WHERE accounting_method NOT IN (?, ?) LIMIT 1", (COUNTING_METHOD, LEGACY_METHOD)).fetchone()
                if unknown:
                    raise StoreUnavailable("Unknown quota accounting method")
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except sqlite3.Error:
            raise StoreUnavailable("Quota storage unavailable") from None

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout, isolation_level=None)
        try:
            connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout * 1000)}")
            connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _transaction(self):
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    # Initialization creates the clock before its first read.
                    connection.execute(SCHEMA[0])
                    value = float(self.clock())
                    if not math.isfinite(value):
                        raise StoreUnavailable("Invalid quota clock")
                    previous = connection.execute("SELECT latest FROM quota_clock WHERE singleton=1").fetchone()
                    now = max(value, previous[0]) if previous else value
                    connection.execute("INSERT INTO quota_clock VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET latest=excluded.latest", (now,))
                    yield connection, now
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except sqlite3.Error:
            raise StoreUnavailable("Quota storage unavailable") from None

    @staticmethod
    def _evict(connection, now):
        return connection.execute("DELETE FROM reservations WHERE state='settled' AND settled_at <= ?", (now - WINDOW_SECONDS,)).rowcount

    def reserve(self, tenant: str, request_id: str, units: int) -> bool:
        if type(units) is not int or units <= 0:
            raise ValueError("Invalid reservation amount")
        with self._transaction() as (connection, now):
            self._evict(connection, now)
            used = connection.execute("SELECT COALESCE(SUM(units), 0) FROM reservations WHERE tenant=?", (tenant,)).fetchone()[0]
            if used + units > LIMIT:
                return False
            connection.execute("INSERT INTO reservations (request_id,tenant,reserved,units,state,created_at,settled_at,accounting_method) VALUES (?, ?, ?, ?, 'active', ?, NULL, ?)", (request_id, tenant, units, units, now, COUNTING_METHOD))
            return True

    def settle(self, request_id: str, actual: int | None = None) -> bool:
        with self._transaction() as (connection, now):
            row = connection.execute("SELECT reserved, state, accounting_method FROM reservations WHERE request_id=?", (request_id,)).fetchone()
            if row is None or row[1] != "active":
                return False  # Idempotent cleanup cannot overwrite a winner.
            if actual is not None and row[2] != COUNTING_METHOD:
                raise ValueError("Legacy reservations require conservative full settlement")
            charge = row[0] if actual is None else actual
            if type(charge) is not int or charge < 0 or charge > row[0]:
                raise ValueError("Invalid reconciliation amount")
            connection.execute("UPDATE reservations SET units=?, state='settled', settled_at=? WHERE request_id=? AND state='active'", (charge, now, request_id))
            self._evict(connection, now)
            return True

    def usage(self, tenant: str) -> int:
        with self._transaction() as (connection, now):
            self._evict(connection, now)
            return connection.execute("SELECT COALESCE(SUM(units), 0) FROM reservations WHERE tenant=?", (tenant,)).fetchone()[0]

    def evict(self) -> int:
        with self._transaction() as (connection, now):
            return self._evict(connection, now)


async def db_call(function, *args):
    """Defer cancellation until the short thread transaction has a known outcome.

    The caller always knows the request ID and can settle after a cancelled
    admission. Cancellation cannot leave a still-running reservation thread
    committing after cleanup has already checked for its row.
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
