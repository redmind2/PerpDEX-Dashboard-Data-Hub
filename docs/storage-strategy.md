# Storage Strategy

This project starts with local SQLite because Phase 1 needs a simple, inspectable data layer before live exchange integrations. SQLite is good for local development, mock data, and early public API collection.

## Current Phase 1 Policy

- Market/orderbook snapshot cadence: 60 seconds per exchange and symbol.
- Market/orderbook retention: 90 days by default.
- Funding retention: keep raw funding rows longer because they are sparse.
- Dashboard uses historical average funding rates rather than showing raw funding rows by default.

## Why Orderbook Data Can Grow

Every market snapshot stores one row in `market_snapshots` plus many rows in `orderbook_levels`.

With the current mock depth:

- 1 snapshot stores 80 orderbook level rows.
- 10 exchanges x 10 markets = 100 exchange/market pairs.
- 1-minute cadence creates 525,600 snapshots per pair per year.
- 100 pairs create 52,560,000 snapshots per year.
- At 80 depth rows each, that is about 4.2 billion orderbook level rows per year.

This is too large for naive long-term SQLite storage.

## Recommended Storage Tiers

### Hot Storage

Use this for active dashboard and recent slippage simulation.

- Store latest 30 to 90 days of orderbook snapshots.
- Keep in SQLite during local development.
- Move to PostgreSQL or TimescaleDB when live collection grows beyond a few exchange/market pairs.

### Warm Summary Storage

Use this for longer-term research and dashboards.

- Store 1m, 5m, 1h summary rows.
- Include spread averages, depth-at-notional, and slippage estimates for fixed notionals.
- Keep for 1 year or more.
- Much smaller than raw orderbook data.

### Cold Archive

Use this only if raw historical orderbook replay is valuable later.

- Export older raw orderbook snapshots to compressed files.
- Prefer Parquet or compressed JSONL.
- Store outside the live DB, for example local disk first and object storage later.
- Query only when doing offline research.

## Future Database Path

Phase 1:

- SQLite local file.
- Mock and early public market data.
- `PERPDEX_DB_PATH` can point each local run at a different SQLite file.

Phase 2:

- Keep SQLite as the default development DB.
- Add a repository boundary so collectors do not care whether storage is SQLite or PostgreSQL.
- Use public exchange APIs first.

Phase 3+:

- Add PostgreSQL or TimescaleDB when collection volume justifies it.
- Keep raw orderbooks for a limited retention window.
- Store long-term summaries separately.
- Optionally archive old raw data to compressed object storage.

## Practical Rule

Do not store raw orderbooks forever in the main DB by default.

For long-running production:

- Raw orderbook: 30 to 90 days.
- Slippage summary: 1 year or longer.
- Funding rates: 1 year or longer.
- Archived raw orderbook: optional, compressed, outside primary DB.

## PostgreSQL / TimescaleDB Extension Shape

The code should keep this boundary:

```text
collector modules
  -> MarketDataRepository methods
    -> SQLite adapter now
    -> PostgreSQL or TimescaleDB adapter later
```

Minimum practical upgrade path:

1. Keep the existing model classes and repository method names.
2. Add a storage adapter interface only when a second backend is actually implemented.
3. Move SQL that is specific to SQLite into the SQLite adapter.
4. Add a PostgreSQL or TimescaleDB adapter with the same repository behavior.
5. Keep collectors unaware of the database backend.

Likely TimescaleDB hypertables later:

- `market_snapshots` partitioned by `timestamp`
- `funding_rates` partitioned by `timestamp`
- optional `orderbook_levels` partitioned through snapshot time or stored as short-retention hot data
- summary tables for spread, depth, and slippage windows

Do not add account, wallet, position, order, or execution tables to this public data hub unless the project scope is explicitly changed.
