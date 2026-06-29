from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .db import SCHEMA
from .models import to_iso


@dataclass(frozen=True)
class ArchiveResult:
    year_month: str
    start: datetime
    end: datetime
    snapshot_rows: int
    orderbook_rows: int
    funding_rows: int
    archive_zip_path: Path | None
    archive_sqlite_path: Path | None
    created: bool
    vacuumed_source: bool


def archive_month(
    source_db_path: Path | str,
    *,
    archive_dir: Path | str = Path("data/archives"),
    month: str | None = None,
    now: date | datetime | None = None,
    keep_sqlite: bool = False,
    force: bool = False,
    vacuum_source: bool = True,
) -> ArchiveResult:
    source_path = Path(source_db_path)
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    year, month_number = _parse_year_month(month) if month else default_archive_year_month(now)
    start, end = month_bounds(year, month_number)
    year_month = f"{year:04d}-{month_number:02d}"

    archive_root = Path(archive_dir)
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_sqlite_path = archive_root / f"perpdex_{year_month}.sqlite"
    archive_zip_path = archive_root / f"perpdex_{year_month}.sqlite.zip"

    with closing(sqlite3.connect(source_path)) as source:
        source.row_factory = sqlite3.Row
        source.execute("PRAGMA foreign_keys = ON")
        counts = _counts_for_month(source, start, end)

    if counts == (0, 0, 0):
        return ArchiveResult(
            year_month=year_month,
            start=start,
            end=end,
            snapshot_rows=0,
            orderbook_rows=0,
            funding_rows=0,
            archive_zip_path=None,
            archive_sqlite_path=None,
            created=False,
            vacuumed_source=False,
        )

    if archive_zip_path.exists() and not force:
        raise FileExistsError(f"Archive already exists: {archive_zip_path}")
    if archive_sqlite_path.exists() and not force:
        raise FileExistsError(f"Archive SQLite already exists: {archive_sqlite_path}")
    if force:
        archive_zip_path.unlink(missing_ok=True)
        archive_sqlite_path.unlink(missing_ok=True)

    _initialize_archive_db(archive_sqlite_path)
    _copy_and_delete_month(source_path, archive_sqlite_path, start, end)
    _vacuum_db(archive_sqlite_path)
    if vacuum_source:
        _vacuum_db(source_path)
    _zip_sqlite(archive_sqlite_path, archive_zip_path)
    if not keep_sqlite:
        archive_sqlite_path.unlink(missing_ok=True)

    return ArchiveResult(
        year_month=year_month,
        start=start,
        end=end,
        snapshot_rows=counts[0],
        orderbook_rows=counts[1],
        funding_rows=counts[2],
        archive_zip_path=archive_zip_path,
        archive_sqlite_path=archive_sqlite_path if keep_sqlite else None,
        created=True,
        vacuumed_source=vacuum_source,
    )


def default_archive_year_month(now: date | datetime | None = None) -> tuple[int, int]:
    current = _as_date(now)
    return _shift_month(current.year, current.month, -2)


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_year, end_month = _shift_month(year, month, 1)
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def _parse_year_month(value: str) -> tuple[int, int]:
    try:
        year_raw, month_raw = value.split("-", 1)
        year = int(year_raw)
        month = int(month_raw)
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM format") from exc
    if month < 1 or month > 12:
        raise ValueError("month must use YYYY-MM format")
    return year, month


def _as_date(value: date | datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    return value


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = year * 12 + (month - 1) + delta
    shifted_year, shifted_month_zero = divmod(zero_based, 12)
    return shifted_year, shifted_month_zero + 1


def _counts_for_month(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime,
) -> tuple[int, int, int]:
    params = (to_iso(start), to_iso(end))
    snapshot_rows = int(
        conn.execute(
            "SELECT COUNT(*) FROM market_snapshots WHERE timestamp >= ? AND timestamp < ?",
            params,
        ).fetchone()[0]
    )
    orderbook_rows = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM orderbook_levels
            WHERE snapshot_id IN (
                SELECT id FROM market_snapshots WHERE timestamp >= ? AND timestamp < ?
            )
            """,
            params,
        ).fetchone()[0]
    )
    funding_rows = int(
        conn.execute(
            "SELECT COUNT(*) FROM funding_rates WHERE timestamp >= ? AND timestamp < ?",
            params,
        ).fetchone()[0]
    )
    return snapshot_rows, orderbook_rows, funding_rows


def _initialize_archive_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as archive:
        archive.executescript(SCHEMA)


def _copy_and_delete_month(source_path: Path, archive_path: Path, start: datetime, end: datetime) -> None:
    params = (to_iso(start), to_iso(end))
    with closing(sqlite3.connect(source_path)) as source:
        source.execute("PRAGMA foreign_keys = ON")
        source.execute("ATTACH DATABASE ? AS archive", (str(archive_path),))
        try:
            source.execute("BEGIN IMMEDIATE")
            source.execute(
                "INSERT INTO archive.market_snapshots SELECT * FROM main.market_snapshots WHERE timestamp >= ? AND timestamp < ?",
                params,
            )
            source.execute(
                """
                INSERT INTO archive.orderbook_levels
                SELECT levels.*
                FROM main.orderbook_levels AS levels
                JOIN main.market_snapshots AS snapshots ON snapshots.id = levels.snapshot_id
                WHERE snapshots.timestamp >= ? AND snapshots.timestamp < ?
                """,
                params,
            )
            source.execute(
                "INSERT INTO archive.funding_rates SELECT * FROM main.funding_rates WHERE timestamp >= ? AND timestamp < ?",
                params,
            )
            source.execute(
                """
                DELETE FROM main.orderbook_levels
                WHERE snapshot_id IN (
                    SELECT id FROM main.market_snapshots WHERE timestamp >= ? AND timestamp < ?
                )
                """,
                params,
            )
            source.execute(
                "DELETE FROM main.market_snapshots WHERE timestamp >= ? AND timestamp < ?",
                params,
            )
            source.execute(
                "DELETE FROM main.funding_rates WHERE timestamp >= ? AND timestamp < ?",
                params,
            )
            source.execute("COMMIT")
        except Exception:
            source.execute("ROLLBACK")
            raise
        finally:
            source.execute("DETACH DATABASE archive")


def _vacuum_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("VACUUM")


def _zip_sqlite(sqlite_path: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive_zip:
        archive_zip.write(sqlite_path, arcname=sqlite_path.name)
