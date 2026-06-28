# Migration Plan

Source repo: `C:\Users\USER\Documents\PerpDEX 파밍봇`
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
- `src/perpdex_farming_bot.egg-info/`
- Python caches

## Scope Guardrail

This repo is public data infrastructure only. It must not add wallet, private key, API key, signature, session key, balance, position, order, cancel, or trade execution features.

## First Verification Commands

```powershell
cd "C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub"
$py = "C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m pytest
.\perpdex.cmd init-db
.\perpdex.cmd seed-mock
.\perpdex.cmd overview
.\perpdex.cmd storage
```

## Future DB Extension

Keep local SQLite compatibility first. Later, add PostgreSQL or TimescaleDB behind the repository/storage layer instead of changing collector or CLI code directly.