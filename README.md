# PerpDEX Dashboard / Data Hub

Public PerpDEX market data collector, SQLite storage layer, CLI dashboard, and future shared data API foundation.

This repo is public data only. It must not contain wallet connection, private keys, API keys, signatures, session keys, balances, positions, orders, cancels, or trade execution.

## Repo Paths

- Active repo: `C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub`
- Obsidian HQ: `C:\Users\USER\Desktop\Pagu's Works\06-Coding\PerpDEX Dashboard Data Hub`

The previous repo was used only as a code reference during migration. The old SQLite DB and logs were not migrated.

## What Was Migrated

- `src/perpdex_bot/`: application code for public collectors, SQLite storage, calculations, and CLI views
- `config/markets.json`: enabled public exchanges and symbols
- `tests/`: automated checks for calculations, collectors, and overview/status output
- `scripts/`: PM2 config, local verification, and secret scanner
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

Run the local verification script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
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
.\perpdex.cmd collect-live --exchange Hotstuff --once
.\perpdex.cmd collect-live --exchange Hyperliquid --once
.\perpdex.cmd collect-live --exchange Lighter --once
.\perpdex.cmd collect-live --exchange Pacifica --once
.\perpdex.cmd status
.\perpdex.cmd overview
```

Do not start long-running collection on this local computer unless you decide to resume local DB accumulation.

## Local SQLite Path

By default, the CLI uses:

```text
data/perpdex_phase1.sqlite
```

To use a different local DB for one PowerShell session:

```powershell
$env:PERPDEX_DB_PATH = "data\my-local.sqlite"
.\perpdex.cmd init-db
```

You can also pass `--db` directly. Put it before the command name because it is a global option:

```powershell
.\perpdex.cmd --db data\my-local.sqlite init-db
```

## Local Runtime Settings

Use `config/markets.json` for exchange and market selection:

- Set an exchange `enabled` value to `false` to disable the whole exchange.
- Remove a symbol from `symbols` to disable one market.

Use `.env` for machine-specific runtime settings. Copy `.env.example` to `.env` and edit local values:

```env
PERPDEX_DB_PATH=data/live-5m-test.sqlite
PERPDEX_COLLECTION_INTERVAL=300
PERPDEX_ORDERBOOK_DEPTH=100
PERPDEX_MAX_NOTIONAL_DEPTH=1000000
PERPDEX_PUBLIC_API_TIMEOUT=20
PERPDEX_PUBLIC_API_RETRIES=3
PERPDEX_COLLECTOR_LOG_PATH=data/logs/collector.log
```

Do not put API keys, private keys, wallet secrets, session keys, or trading credentials in `.env`.

## Useful Commands

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
.\perpdex.cmd init-db
.\perpdex.cmd seed-mock
.\perpdex.cmd overview
.\perpdex.cmd overview --failed-only
.\perpdex.cmd status
.\perpdex.cmd status --failed-only
powershell -ExecutionPolicy Bypass -File .\scripts\live-test-loop.ps1
.\perpdex.cmd dashboard --exchange Hibachi --symbol BTC-PERP
.\perpdex.cmd funding-history --exchange Hibachi --symbol BTC-PERP --limit 12
.\perpdex.cmd slippage --exchange Hibachi --symbol BTC-PERP
.\perpdex.cmd storage
.\perpdex.cmd prune --days 90

# Short-symbol cross-exchange views:
.\perpdex.cmd spreads --symbol BTC
.\perpdex.cmd slippage --symbol BTC
.\perpdex.cmd orderspread --symbol BTC
.\perpdex.cmd funding --symbol BTC
.\perpdex.cmd funding-history --symbol BTC
.\perpdex.cmd dashboard --symbol BTC
```

## Telegram Health Monitor

The Telegram monitor is local alerting only. Keep the real bot token and chat id in `.env`; do not commit them. It sends an OK status every 6 hours and alerts within the next check interval only for critical issues such as the collector process stopping, the DB becoming unreadable, or the latest DB snapshot becoming stale. Routine per-market collection failures and matching error lines in live logs are summarized as counts in the 6-hour status report instead of being sent as immediate alerts.

Add these local `.env` values:

```env
PERPDEX_TELEGRAM_BOT_TOKEN=
PERPDEX_TELEGRAM_CHAT_ID=
PERPDEX_TELEGRAM_STATUS_INTERVAL=21600
PERPDEX_TELEGRAM_CHECK_INTERVAL=60
PERPDEX_TELEGRAM_COMMAND_INTERVAL=2
PERPDEX_TELEGRAM_ALERT_COOLDOWN=900
PERPDEX_TELEGRAM_STALE_AFTER=900
PERPDEX_LIVE_PID_PATH=data/live-test.pid
PERPDEX_LIVE_RUNNER_LOG_PATH=data/logs/live-test-runner.log
```

Telegram commands:

```text
/help - show command list
/status - show collector and DB health
/storage - show DB size and row counts
/markets - show monitored exchanges and markets
/failures - show active collector failures
/control - show current pause controls
/pause - pause all collection
/resume - resume all collection and clear exchange pauses
/pause Pacifica - pause one exchange
/resume Pacifica - resume one exchange
/slippage BTC - show simple slippage rows across exchanges
/slippage Hibachi BTC - show simple slippage for one market
/orderspread - show $100k order-size spread rows for every market
/orderspread BTC - show $100k order-size spread rows across exchanges
/orderspread Hibachi - show $100k order-size spread rows for one exchange
/orderspread Hibachi BTC - show order-size spread details
/spreads - show spread rows for every monitored market
/spreads Hibachi - show spread rows for one exchange
/spreads BTC - show spread rows for one market across exchanges
/spreads Hibachi BTC - show one market's current and average spreads
```

Preview one monitor message without sending Telegram:

```powershell
.\perpdex.cmd telegram-monitor --once --dry-run
```

Run the monitor in the current PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\telegram-monitor.ps1
```

Run the monitor hidden in the background:

```powershell
Start-Process powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','.\scripts\telegram-monitor.ps1') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
```

Stop the monitor:

```powershell
Stop-Process -Id (Get-Content data\telegram-monitor.pid)
```

## Current Public Collectors

- Hibachi: `BTC-PERP`, `ETH-PERP`, `EUR-PERP`, `SOL-PERP`, `HYPE-PERP`
- Rise: `BTC-PERP`, `ETH-PERP`, `HYPE-PERP`, `SOL-PERP`
- Hotstuff: `BTC-PERP`, `ETH-PERP`, `HYPE-PERP`, `SOL-PERP`, `SILVER-PERP`, `WTIOIL-PERP`, `GOLD-PERP`, `BRENTOIL-PERP`
- Hyperliquid: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `SAMSUNG-PERP`, `SKHYNICS-PERP`, `EWY-PERP`, `WTIOIL-PERP`, `BRENTOIL-PERP`, `GOLD-PERP`, `SILVER-PERP`
- Lighter: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `SAMSUNG-PERP`, `SKHYNICS-PERP`, `EWY-PERP`, `WTI-PERP`, `BRENT-PERP`, `XAU-PERP`, `PAXG-PERP`, `XAG-PERP`
- Pacifica: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `GOLD-PERP`, `PAXG-PERP`, `CL-PERP`, `SILVER-PERP`, `SKHYNIX-PERP`, `SAMSUNG-PERP`

Older notes may call Rise `RiseX`, but the CLI exchange id is `Rise`.

## Orderbook Storage Depth

`collect-live` supports two orderbook depth controls:

- `--depth`: max levels to request from the exchange when the exchange supports a limit.
- `--max-notional-depth`: max USD notional to save per side after collection.

Example: collect one Pacifica pass and save about `$1M` bid depth plus `$1M` ask depth per market:

```powershell
.\perpdex.cmd collect-live --exchange Pacifica --once --depth 100 --max-notional-depth 1000000
```

When `--max-notional-depth 1000000` is set, the collector keeps levels until cumulative level notional reaches at least `$1,000,000` on bids and at least `$1,000,000` on asks. If the first level alone is larger than the target, it still keeps that first level.

Hotstuff uses REST for this collector. The WebSocket API is better for continuous streaming later, but REST is simpler and more reliable for the current 5-minute SQLite collection loop.

Hyperliquid also uses direct REST `/info` public endpoints. The Python SDK and CCXT are useful for broader integrations, but they add dependencies and include trading/account surfaces that this public data hub does not need.

Lighter uses direct REST public endpoints under `https://mainnet.zklighter.elliot.ai/api/v1`. The Python SDK is useful for broader integrations, but REST is enough for this public collector and avoids adding signer/trading-account surfaces.

Pacifica uses direct REST public endpoints under `https://api.pacifica.fi/api/v1`. The Python SDK is useful for broader integrations, but the REST API already exposes public market info, prices, funding, and order books for the current collector. Pacifica's public REST book returns up to 10 levels per side; the collector requests `agg_level=100` by default through `PERPDEX_PACIFICA_ORDERBOOK_AGG_LEVEL` so order-size spread estimates use a wider aggregated book. Supported values are `1`, `10`, `100`, `1000`, and `10000`.

Hyperliquid non-core market mappings:

- `SAMSUNG-PERP` -> `xyz:SMSN`
- `SKHYNICS-PERP` -> `xyz:SKHX`
- `WTIOIL-PERP` -> `cash:WTI`
- `BRENTOIL-PERP` -> `xyz:BRENTOIL`
- `GOLD-PERP` -> `xyz:GOLD`
- `SILVER-PERP` -> `xyz:SILVER`

Lighter market mappings:

- `SAMSUNG-PERP` -> `SAMSUNGUSD`
- `SKHYNICS-PERP` -> `SKHYNIXUSD`
- `BRENT-PERP` -> `BRENTOIL`
- `XAU-PERP` -> `XAU`
- `XAG-PERP` -> `XAG`

Pacifica market mappings:

- `GOLD-PERP` -> `XAU`
- `SILVER-PERP` -> `XAG`
- `CL-PERP` -> `CL`
- `SKHYNIX-PERP` -> `SKHYNIX`
- `SAMSUNG-PERP` -> `SAMSUNG`

## Hibachi EUR-PERP Orderbook Policy

If Hibachi returns a null or empty orderbook for `EUR-PERP`, the collector must not save a fake market snapshot. It records a collector failure, leaves the market visible in `status` / `overview`, and retries on the next collection pass.

This is safer than filling missing bids or asks with zeroes because fake orderbook rows would make spread and slippage numbers misleading.

## Monthly SQLite Archive

For local SQLite, the intended live cadence is 5 minutes. Because a 1-minute spread window usually has fewer than two samples at that cadence, the repository reports `n/a` for 1m average spread until at least two samples exist in that window.

On the first day of each month, archive the month from two months earlier:

```powershell
.\perpdex.cmd archive-month
```

Example: on July 1, this archives May data into `data/archives/perpdex_YYYY-MM.sqlite.zip`, deletes those May raw rows from the active DB, and vacuums the active DB so the file can shrink. For a calendar test or manual test, pass `--now 2026-07-01` or archive a specific month with `--month 2026-05`.

For server automation, `scripts/archive-monthly.ps1` runs the same archive command and writes `data/logs/archive-monthly.log`. Register it in Windows Task Scheduler to run monthly:

```powershell
schtasks.exe /Create /TN "PerpDEX Monthly Archive" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\redmi\Documents\PerpDEX-Dashboard-Data-Hub\scripts\archive-monthly.ps1" /SC MONTHLY /D 1 /ST 03:30 /F
```

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
