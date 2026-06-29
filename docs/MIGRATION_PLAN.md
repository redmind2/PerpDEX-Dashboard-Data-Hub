# Migration Plan

Source: previous PerpDEX implementation, used as a code reference only.
Target repo: `C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub`

## Goal

Move only the public market data collector, local storage, CLI dashboard, tests, settings, and docs into the new data hub repo.

Do not move real SQLite data or logs.

## Migrated

- `src/perpdex_bot/`
- `tests/`
- `config/markets.json`
- `scripts/pm2-collector.config.cjs`
- `scripts/scan_secrets.py`
- `docs/storage-strategy.md`
- `pyproject.toml`
- `perpdex.cmd`
- `.env.example`

## Excluded

- `data/`
- `*.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`
- logs
- old package metadata such as `egg-info/`
- Python caches

## Scope Guardrail

This repo is public data infrastructure only. It must not add wallet, private key, API key, signature, session key, balance, position, order, cancel, or trade execution features.

## Verification Commands

```powershell
cd "C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub"
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

When `pytest` is installed, `verify.ps1` runs the full test suite. When it is not installed, it runs syntax checks, SQLite CLI smoke tests, overview rendering, storage counts, and the tracked-file secret scan.

## Future DB Extension

Keep local SQLite compatibility first. Later, add PostgreSQL or TimescaleDB behind the repository/storage layer instead of changing collector or CLI code directly.
