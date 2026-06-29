# Verification

Use this project-level command first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

## What It Checks

The script uses the bundled Python runtime when it exists, sets `PYTHONPATH` to `src`, and uses a local verification DB:

```text
data/phase1-verify.sqlite
```

It then runs:

1. Python syntax compilation for `src` and `tests`.
2. Full `pytest` suite when `pytest` is installed.
3. Fallback smoke checks when `pytest` is missing:
   - initialize SQLite schema
   - seed mock data
   - render `overview`
   - show `storage`
   - run tracked-file secret scan

## Why There Is A Fallback

Some local Windows environments have Python available but do not have `pytest` installed. In that case, a missing test tool should not be confused with broken project code.

The fallback is not a full replacement for pytest. It is a quick safety check that proves the package imports, the database schema initializes, mock data can be saved, and the main CLI views can run.

## Direct pytest Command

When pytest is available:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest
```

## Direct CLI Smoke Commands

```powershell
$env:PERPDEX_DB_PATH = "data\phase1-smoke.sqlite"
.\perpdex.cmd init-db
.\perpdex.cmd seed-mock
.\perpdex.cmd overview
.\perpdex.cmd storage
python scripts\scan_secrets.py
```

## One-Time Live Public Collector Smoke

Use a separate DB when checking a newly added exchange:

```powershell
.\perpdex.cmd --db data\lighter-smoke.sqlite init-db
.\perpdex.cmd --db data\lighter-smoke.sqlite collect-live --exchange Lighter --once --timeout 20
.\perpdex.cmd --db data\lighter-smoke.sqlite status --exchange Lighter
.\perpdex.cmd --db data\lighter-smoke.sqlite overview --failed-only
.\perpdex.cmd --db data\lighter-smoke.sqlite storage
```

For Pacifica:

```powershell
.\perpdex.cmd --db data\pacifica-smoke.sqlite init-db
.\perpdex.cmd --db data\pacifica-smoke.sqlite collect-live --exchange Pacifica --once --timeout 20
.\perpdex.cmd --db data\pacifica-smoke.sqlite status --exchange Pacifica
.\perpdex.cmd --db data\pacifica-smoke.sqlite overview --failed-only
.\perpdex.cmd --db data\pacifica-smoke.sqlite storage
```

For orderbook notional-depth storage:

```powershell
.\perpdex.cmd --db data\notional-depth-smoke.sqlite init-db
.\perpdex.cmd --db data\notional-depth-smoke.sqlite collect-live --exchange Pacifica --symbol BTC-PERP --once --depth 100 --max-notional-depth 1000000 --timeout 20
.\perpdex.cmd --db data\notional-depth-smoke.sqlite storage
```
