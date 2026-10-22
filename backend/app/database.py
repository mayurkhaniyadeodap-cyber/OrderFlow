"""SQLite engine/session setup and in-place schema upgrades."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

# pyright: reportMissingImports=false
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger("orderflow.database")


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
_engine: Engine | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def snapshot_database(db_path: Path, target: Path) -> Path:
    """Consistent copy of a live SQLite database (includes WAL contents) using the backup API."""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def _copy_user_rows(cur: sqlite3.Cursor, cols: str) -> None:
    """Copy users into the rebuilt table (separate function so tests can simulate a failure here)."""
    cur.execute(f"INSERT INTO users ({cols}) SELECT {cols} FROM users_pre_admin")


def _upgrade_schema(db_path: Path, backup_dir: Path | None) -> None:
    """Upgrade databases created before the Admin role existed. Keeps every row and id; never drops data.

    The old users table has CHECK (role in ('sales','printing')), which SQLite cannot alter, so the table is
    rebuilt once: rename -> create new -> copy rows -> drop old. This runs on a plain sqlite3 connection in an
    explicit BEGIN IMMEDIATE ... COMMIT transaction (the default driver mode does not wrap DDL in a transaction),
    so a failure part-way leaves the original table untouched. A safety snapshot is taken first.
    """
    from sqlalchemy.dialects import sqlite as sqlite_dialect
    from sqlalchemy.schema import CreateIndex, CreateTable

    from .models import User

    if not db_path.exists():
        return
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=30)
    try:
        tables = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        if "users_pre_admin" in tables:
            # Left over from an interrupted upgrade by an earlier build: put the original table back first.
            users_rows = con.execute("SELECT count(*) FROM users").fetchone()[0] if "users" in tables else 0
            if users_rows == 0:
                con.execute("BEGIN IMMEDIATE")
                try:
                    if "users" in tables:
                        con.execute("DROP TABLE users")
                    con.execute("ALTER TABLE users_pre_admin RENAME TO users")
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                log.warning("Restored the users table from an interrupted upgrade (users_pre_admin).")
                tables = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
            else:
                log.warning("Table users_pre_admin exists next to a non-empty users table; left untouched.")
                return
        if "users" not in tables or "'admin'" in (tables["users"] or ""):
            return  # new database, or already upgraded

        if backup_dir is not None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved = snapshot_database(db_path, backup_dir / f"pre_admin_upgrade_{stamp}.db")
            log.warning("Upgrading users table for the Admin role; safety copy saved to %s", saved)

        dialect = sqlite_dialect.dialect()
        create_table = str(CreateTable(User.__table__).compile(dialect=dialect))
        create_indexes = [str(CreateIndex(ix).compile(dialect=dialect)) for ix in User.__table__.indexes]
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            old_cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
            before = cur.execute("SELECT count(*) FROM users").fetchone()[0]
            cur.execute("ALTER TABLE users RENAME TO users_pre_admin")
            cur.execute("DROP INDEX IF EXISTS ix_users_username")
            cur.execute(create_table)
            for ddl in create_indexes:
                cur.execute(ddl)
            _copy_user_rows(cur, ", ".join(c for c in old_cols if c in User.__table__.c))
            after = cur.execute("SELECT count(*) FROM users").fetchone()[0]
            if after != before:
                raise RuntimeError(f"users upgrade copied {after} of {before} rows")
            cur.execute("DROP TABLE users_pre_admin")
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")  # original users table and data are left exactly as they were
            raise
    finally:
        con.close()


def configure_database(path: Path, backup_dir: Path | None = None) -> Engine:
    """(Re)bind the session factory to a SQLite file, upgrade old schemas and create missing tables."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(_engine, "connect", _sqlite_pragmas)
    SessionLocal.configure(bind=_engine)
    from . import models  # noqa: F401  (register tables)

    _upgrade_schema(path, backup_dir)
    _snapshot_before_new_tables(path, backup_dir)
    Base.metadata.create_all(_engine)
    _add_missing_columns(path, backup_dir)
    return _engine


def _add_missing_columns(db_path: Path, backup_dir: Path | None) -> None:
    """Add columns introduced by an update to existing tables (create_all only creates missing tables).

    Only nullable columns without defaults are added, so existing rows simply get NULL; nothing is dropped or
    rewritten. A safety snapshot is taken first, and all ALTERs run in one transaction.
    """
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    if not db_path.exists():
        return
    dialect = sqlite_dialect.dialect()
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=30)
    try:
        missing: list[tuple[str, str, str]] = []
        for table in Base.metadata.sorted_tables:
            have = {r[1] for r in con.execute(f'PRAGMA table_info("{table.name}")')}
            if not have:
                continue
            for col in table.columns:
                if col.name not in have:
                    if not col.nullable:
                        raise RuntimeError(f"Cannot add required column {table.name}.{col.name} automatically.")
                    missing.append((table.name, col.name, col.type.compile(dialect=dialect)))
        if not missing:
            return
        if backup_dir is not None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved = snapshot_database(db_path, backup_dir / f"pre_column_update_{stamp}.db")
            log.warning("Adding column(s) %s; safety copy saved to %s",
                        ", ".join(f"{t}.{c}" for t, c, _ in missing), saved)
        con.execute("BEGIN IMMEDIATE")
        try:
            for table_name, col_name, col_type in missing:
                con.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type}')
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def _snapshot_before_new_tables(db_path: Path, backup_dir: Path | None) -> None:
    """Back up an existing database before create_all adds tables introduced by an update."""
    if backup_dir is None or not db_path.exists():
        return
    con = sqlite3.connect(str(db_path))
    try:
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    if not existing:
        return  # brand-new database
    missing = sorted(set(Base.metadata.tables) - existing)
    if missing:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved = snapshot_database(db_path, backup_dir / f"pre_schema_update_{stamp}.db")
        log.warning("Adding table(s) %s; safety copy saved to %s", ", ".join(missing), saved)


def get_engine() -> Engine:
    assert _engine is not None, "Database not configured"
    return _engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
