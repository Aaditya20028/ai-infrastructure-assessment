import sqlite3


def test_sqlite_persists_on_disk(tmp_path):
    path = tmp_path / "environment.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE probe (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO probe VALUES (?)", (7,))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM probe").fetchone() == (7,)
