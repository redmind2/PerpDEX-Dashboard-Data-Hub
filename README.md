# PerpDEX Dashboard / Data Hub

Public PerpDEX market data collector, SQLite storage layer, CLI dashboard, and future shared data API foundation.

This repo is public data only. It must not contain wallet connection, private keys, API keys, signatures, session keys, balances, positions, orders, cancels, or trade execution.

## Repo Paths

- Active repo: `C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub`
- Obsidian HQ: `C:\Users\USER\Desktop\Pagu's Works\06-Coding\PerpDEX Dashboard Data Hub`
- Previous reference repo: `C:\Users\USER\Documents\PerpDEX 파밍봇`

The old repo was used only as a code reference. The old SQLite DB and logs were not migrated.

## What Was Migrated

- `src/perpdex_bot/`: application code for public collectors, SQLite storage, calculations, and CLI views
- `config/markets.json`: enabled public exchanges and symbols
- `tests/`: automated checks for calculations, collectors, and overview/status output
- `scripts/`: PM2 config and secret scanner
- `docs/storage-strategy.md`: SQLite retention and future database scaling notes
- `perpdex.cmd`: Windows helper so commands are shorter
- `.env.example`: local DB path template without secrets

## What Was Not Migrated

- `data/`
- SQLite DB files such as `*.sqlite`, `*.sqlite-wal`, and `*.sqlite-shm`
- log files
- Python build/cache folders such as `egg-info`, `__pycache__`, and `.pytest_cache`

## Beginner Mental Model

Think of this project as four simple layers:

1. Collector: asks public exchange endpoints for market data.
2. Database: saves the public market data locally in SQLite.
3. Repository/calculation code: reads the saved data and computes spreads, funding, and slippage.
4. CLI dashboard: prints useful views such as `overview`, `status`, `dashboard`, and `storage`.

No layer is allowed to trade or touch private account data.

## Quick Start

Open PowerShell in this folder:

```powershell
cd "C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub"
```

Use the bundled Python runtime:

```powershell
$py = "C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m pip install -e .
```

Create a fresh local SQLite DB:

```powershell
.\perpdex.cmd init-db
```

Optional: insert mock sample data for local dashboard testing:

```powershell
.\perpdex.cmd seed-mock
.\perpdex.cmd overview
.\perpdex.cmd dashboard
```

One-time public collector smoke tests:

```powershell
.\perpdex.cmd collect-live --exchange Hibachi --once
.\perpdex.cmd collect-live --exchange Rise --once
.\perpdex.cmd status
.\perpdex.cmd overview
```

Do not start long-running collection on this local computer unless you decide to resume local DB accumulation.

## Useful Commands

```powershell
.\perpdex.cmd init-db
.\perpdex.cmd seed-mock
.\perpdex.cmd overview
.\perpdex.cmd overview --failed-only
.\perpdex.cmd status
.\perpdex.cmd status --failed-only
.\perpdex.cmd dashboard --exchange Hibachi --symbol BTC-PERP
.\perpdex.cmd funding-history --exchange Hibachi --symbol BTC-PERP --limit 12
.\perpdex.cmd slippage --exchange Hibachi --symbol BTC-PERP
.\perpdex.cmd storage
.\perpdex.cmd prune --days 90
```

## Current Public Collectors

- Hibachi: `BTC-PERP`, `ETH-PERP`, `EUR-PERP`
- Rise: `BTC-PERP`, mapped to public BTC/USDC market data with `market_id` 1

## Future Database Direction

SQLite remains the first supported local database because it is simple and works without a server. The code should continue to keep DB access behind repository functions so a future PostgreSQL or TimescaleDB backend can be added without rewriting the CLI and collector logic.

Recommended future shape:

```text
CLI / dashboard / future API
  -> repository layer
    -> SQLite backend now
    -> PostgreSQL or TimescaleDB backend later
```

See `docs/storage-strategy.md` for retention and scaling notes.