# Codex Start Prompt - PerpDEX Dashboard / Data Hub

You are working on the `PerpDEX Dashboard / Data Hub` project.

## Repo

`C:\Users\USER\Documents\PerpDEX-Dashboard-Data-Hub`

## Obsidian HQ

`C:\Users\USER\Desktop\Pagu's Works\06-Coding\PerpDEX Dashboard Data Hub`

## Scope

This project is a public market data collector, local SQLite storage layer, CLI dashboard, and future shared data API foundation.

Do not add wallet connection, private key, API key, signature, session key, balance, position, order, cancel, or trade execution features.

## Config Split

- Use `config\markets.json` for exchange and market selection.
- Use `.env` for local runtime settings: DB path, collection interval, orderbook request depth, saved notional depth, API timeout/retries, and collector log path.
- Do not put API keys, private keys, wallet secrets, session keys, or trading credentials in `.env`.

## Current Public Collectors

- Hibachi public collector: `BTC-PERP`, `ETH-PERP`, `EUR-PERP`, `SOL-PERP`, `HYPE-PERP`
- Rise public collector: `BTC-PERP`, `ETH-PERP`, `HYPE-PERP`, `SOL-PERP`
- Hotstuff public collector: `BTC-PERP`, `ETH-PERP`, `HYPE-PERP`, `SOL-PERP`, `SILVER-PERP`, `WTIOIL-PERP`, `GOLD-PERP`, `BRENTOIL-PERP`
- Hyperliquid public collector: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `SAMSUNG-PERP`, `SKHYNICS-PERP`, `EWY-PERP`, `WTIOIL-PERP`, `BRENTOIL-PERP`, `GOLD-PERP`, `SILVER-PERP`
- Lighter public collector: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `SAMSUNG-PERP`, `SKHYNICS-PERP`, `EWY-PERP`, `WTI-PERP`, `BRENT-PERP`, `XAU-PERP`, `PAXG-PERP`, `XAG-PERP`
- Pacifica public collector: `BTC-PERP`, `ETH-PERP`, `SOL-PERP`, `HYPE-PERP`, `GOLD-PERP`, `PAXG-PERP`, `CL-PERP`, `SILVER-PERP`, `SKHYNIX-PERP`, `SAMSUNG-PERP`
- Older notes may say `RiseX`; use `Rise` as the CLI exchange id.

## Current CLI

- `init-db`
- `seed-mock`
- `collect-live`
- `overview`
- `status`
- `dashboard`
- `storage`
- `prune`

## Local DB

Default DB path:

```text
data/perpdex_phase1.sqlite
```

Override with:

```powershell
$env:PERPDEX_DB_PATH = "data\my-local.sqlite"
```

Or pass `--db` before the command name:

```powershell
.\perpdex.cmd --db data\my-local.sqlite init-db
```

Suggested live-test `.env`:

```env
PERPDEX_DB_PATH=data/live-30s-test.sqlite
PERPDEX_COLLECTION_INTERVAL=30
PERPDEX_ORDERBOOK_DEPTH=100
PERPDEX_MAX_NOTIONAL_DEPTH=1000000
PERPDEX_PUBLIC_API_TIMEOUT=20
PERPDEX_PUBLIC_API_RETRIES=3
PERPDEX_COLLECTOR_LOG_PATH=data/logs/collector.log
```

## Verification

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

If `pytest` exists, this runs the full test suite. If `pytest` is missing, it runs fallback checks: syntax compile, SQLite init/seed, overview, storage, and secret scan.

## Current Policy Decisions

- Keep SQLite as the default local database for Phase 1.
- Keep repository functions as the storage boundary so PostgreSQL or TimescaleDB can be added later.
- For live test collection, prefer `--interval 30 --depth 100 --max-notional-depth 1000000` to test 30-second polling with about `$1M` stored depth per side.
- For later conservative server collection, prefer `--interval 300 --depth 100 --max-notional-depth 1000000` unless measured DB growth is too high.
- `--depth` controls how many levels to request when an exchange supports a limit; `--max-notional-depth` trims saved bid/ask levels by cumulative USD notional per side.
- Do not migrate old `data/`, SQLite files, or logs.
- Treat Hibachi `EUR-PERP` null orderbook responses as temporary public API gaps: do not save fake snapshots; record collector failure and retry later.
- Use Hotstuff REST `/info` public methods for the current collector. Keep WebSocket for a future streaming task.
- Use Hyperliquid direct REST `/info` public methods. Do not add SDK, CCXT, wallet, signing, or exchange endpoint features unless scope changes.
- Hyperliquid maps `SAMSUNG-PERP` to `xyz:SMSN`, `SKHYNICS-PERP` to `xyz:SKHX`, and `WTIOIL-PERP` to `cash:WTI`.
- Use Lighter direct REST public endpoints under `https://mainnet.zklighter.elliot.ai/api/v1`. Do not add the SDK unless a future task needs SDK-only public data.
- Lighter maps `SAMSUNG-PERP` to active `SAMSUNGUSD`, `SKHYNICS-PERP` to active `SKHYNIXUSD`, and `BRENT-PERP` to active `BRENTOIL`.
- Use Pacifica direct REST public endpoints under `https://api.pacifica.fi/api/v1`. Do not add the SDK unless a future task needs SDK-only public data.
- Pacifica maps `GOLD-PERP` to `XAU`, `SILVER-PERP` to `XAG`, and keeps `CL-PERP`, `SKHYNIX-PERP`, and `SAMSUNG-PERP` as direct symbols.
