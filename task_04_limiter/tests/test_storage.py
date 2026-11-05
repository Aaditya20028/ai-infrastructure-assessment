from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3

import pytest

from task_04_limiter.devtools import process_probe
from task_04_limiter.storage import LIMIT, QuotaStore, StoreUnavailable
from task_04_limiter.tokenization import COUNTING_METHOD, LEGACY_METHOD


def test_under_exact_and_above_limit(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "first", 49999)
    assert store.reserve("a", "last", 1)
    assert not store.reserve("a", "over", 1)
    assert store.usage("a") == LIMIT


def test_single_above_limit_does_not_create_record(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert not store.reserve("a", "too-big", 50001)
    assert store.usage("a") == 0


def test_true_rolling_window_and_exact_eviction_boundary(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "old", 30000)
    store.settle("old")
    clock.advance(30)
    assert store.reserve("a", "new", 20000)
    store.settle("new")
    clock.now = 159.999
    assert not store.reserve("a", "early", 1)
    clock.now = 160
    assert store.evict() == 1
    assert store.usage("a") == 20000
    assert store.reserve("a", "reuse", 30000)
    assert not store.reserve("a", "over", 1)


def test_calendar_minute_does_not_reset_usage(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "start", 50000)
    store.settle("start")
    clock.now = 121  # New calendar minute, but only 21 seconds elapsed.
    assert not store.reserve("a", "not-yet", 1)


def test_active_reservation_never_evicted_mid_request(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "active", 50000)
    clock.advance(120)
    assert store.evict() == 0
    assert not store.reserve("a", "blocked", 1)
    assert store.settle("active", 100)
    clock.advance(59.999)
    assert store.usage("a") == 100
    clock.advance(0.001)
    assert store.usage("a") == 0


def test_expired_settlements_do_not_release_active_holds(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "settled", 25000)
    store.settle("settled")
    assert store.reserve("a", "running", 25000)
    clock.advance(61)
    assert store.evict() == 1
    assert store.usage("a") == 25000
    assert store.reserve("a", "fits", 25000)
    assert not store.reserve("a", "no", 1)


def test_tenant_independence_and_persistence(tmp_path, clock):
    path = tmp_path / "persistent.sqlite3"
    store = QuotaStore(path, clock=clock)
    assert store.reserve("a", "a1", LIMIT)
    assert store.reserve("b", "b1", LIMIT)
    store.settle("a1", 1234)
    reopened = QuotaStore(path, clock=clock)
    assert reopened.usage("a") == 1234
    assert reopened.usage("b") == LIMIT  # Active/orphan survives restart too.
    assert not reopened.reserve("b", "b2", 1)


def test_reconciliation_is_idempotent_and_bounded(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "request", 1000)
    assert store.settle("request", 100)
    assert not store.settle("request")
    assert not store.settle("missing")
    assert store.usage("a") == 100
    assert store.reserve("a", "bad", 10)
    for invalid in (-1, 11, True, "1"):
        with pytest.raises(ValueError):
            store.settle("bad", invalid)
    assert store.usage("a") == 110


def test_concurrent_connections_never_over_admit(tmp_path, clock):
    path = tmp_path / "concurrent.db"
    store = QuotaStore(path, clock=clock)

    def reserve(index):
        return QuotaStore(path, clock=clock).reserve("tenant", str(index), 1000)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(reserve, range(80)))
    assert sum(decisions) == 50
    assert store.usage("tenant") == 50000


def test_real_spawned_processes_share_atomic_quota(tmp_path):
    result = process_probe(tmp_path / "process.db", workers=4, attempts=20, units=1000)
    assert result["workers_used"] == 4
    assert result["attempts"] == 80 and result["admitted"] == 50
    assert result["usage"] == 50000


def test_clock_rollback_is_clamped_conservatively(tmp_path, clock):
    store = QuotaStore(tmp_path / "quota.db", clock=clock)
    assert store.reserve("a", "one", 50000)
    store.settle("one")
    clock.now = 50
    assert store.usage("a") == 50000
    clock.now = 159
    assert not store.reserve("a", "too-soon", 1)


def test_busy_database_fails_closed(tmp_path, clock):
    store = QuotaStore(tmp_path / "busy.db", clock=clock, busy_timeout=0.02)
    with closing(sqlite3.connect(store.path, isolation_level=None)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(StoreUnavailable):
                store.reserve("a", "blocked", 1)
        finally:
            lock.rollback()
    assert store.usage("a") == 0


def test_schema_wal_indexes_and_unknown_version(tmp_path, clock):
    path = tmp_path / "schema.db"
    QuotaStore(path, clock=clock)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        names = {row[1] for row in connection.execute("PRAGMA index_list(reservations)")}
        assert {"quota_tenant", "quota_expiry"} <= names
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(StoreUnavailable):
        QuotaStore(path, clock=clock)


@pytest.mark.parametrize("path", [":memory:", "file::memory:?cache=shared"])
def test_memory_databases_rejected(path):
    with pytest.raises(ValueError):
        QuotaStore(path)


def test_version_one_migration_preserves_conservative_charges_and_active_holds(tmp_path, clock):
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE reservations (request_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,reserved INTEGER NOT NULL,units INTEGER NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,settled_at REAL)")
        connection.execute("INSERT INTO reservations VALUES ('active','a',100,100,'active',100,NULL)")
        connection.execute("INSERT INTO reservations VALUES ('settled','a',400,400,'settled',100,100)")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    store = QuotaStore(path, clock=clock)
    assert store.usage("a") == 500
    assert store.reserve("a", "new", 49500)
    assert not store.reserve("a", "over", 1)
    with pytest.raises(ValueError):
        store.settle("active", 1)  # No guessed byte->token reinterpretation.
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        methods = dict(connection.execute("SELECT request_id,accounting_method FROM reservations"))
    assert methods == {"active": LEGACY_METHOD, "settled": LEGACY_METHOD, "new": COUNTING_METHOD}
    clock.advance(60)
    assert store.evict() == 1 and store.usage("a") == 49600
    assert store.settle("active")  # Explicit full settlement remains safe.
    assert QuotaStore(path, clock=clock).usage("a") == 49600
