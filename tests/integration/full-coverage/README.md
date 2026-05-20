# full-coverage integration package

A single sprawling `pipeline.betl.yml` that exercises every feature the
betl.yaml format supports. The point is to **stress-test the yaml-ui
renderer** against a maximally varied input — every transform, every
sink, both connection types, every control-flow shape — and as a side
benefit prove the same YAML runs end-to-end against live databases.

## What it covers

**Connections** — postgres + mssql, DSNs sourced from env.
**Parameters** — `string`, `int64`, `date`, `bool` (one of each).
**Control flow** — `dataflow`, `foreach (over / over_glob / over_query)`,
  task stages, `after:` ordering, `condition:` skipping, `on_failure:`.
**Expressions** — `lang: lua` and `lang: ssisexpr` in both `map.add`
  and `filter.where`.
**Dataflow sources** — `csv.read`, `json.read`, `xml.read`,
  `postgres.read`, `mssql.read`, `xlsx.read`, `betl.gen_int64`,
  `betl.gen_strings`.
**Dataflow transforms** — `filter`, `map` (add + select), `audit`,
  `multicast`, `join`, `conditional_split`, `union`, `sort`, `distinct`,
  `limit`, `pivot`, `unpivot`, `aggregate`, `postgres.lookup`,
  `mssql.lookup`, `postgres.exec`, `mssql.exec` shape.
**Dataflow sinks** — `postgres.copy`, `postgres.upsert`, `mssql.upsert`,
  `mssql.bulkinsert` (array mode), `csv.write`, `xlsx.write`,
  `json.write`, `betl.count_rows`.
**Tasks** — `sql.execute`, `var.set` (literal + sql mode), `shell`,
  `file.copy`, `file.move`, `file.delete`, `http.get`, `http.post`,
  `smtp.send`, `lua.task`, `dotnet.task`.

## Layout

```
.
├── README.md           — this file
├── pipeline.betl.yml   — the kitchen sink
├── fixtures/           — inputs the pipeline reads
│   ├── orders-today.csv
│   ├── inventory.xml
│   ├── api-orders.ndjson
│   ├── http-body.json    (used by http.post body_file)
│   ├── smtp-body.txt     (used by smtp.send body_file)
│   └── seed.txt          (touched by file.copy / file.move / file.delete)
├── out/                — pipeline writes here (csv.write / xlsx.write / json.write)
└── tmp/                — file.copy / file.move / file.delete scratch
```

## Bootstrap

The two databases are populated by the integration harness (or by hand
via the `db-postgres` / `db-mssql` MCPs in the dev sandbox). DDL +
seed-row SQL is in [`schemas.md`](schemas.md) for the record.

Both databases are named `betl_coverage`. Once-only setup (assuming
both servers are already running on the host):

```sh
psql ... -d betl_coverage -f schemas.postgres.sql
sqlcmd ... -d betl_coverage -i schemas.mssql.sql
```

## Run it

```sh
export BETL_TEST_PG_DSN="host=localhost port=5432 user=postgres dbname=betl_coverage"
export BETL_TEST_MSSQL_DSN="Driver={ODBC Driver 18 for SQL Server};Server=localhost,1433;Uid=sa;Pwd=...;Database=betl_coverage;TrustServerCertificate=yes"

cd tests/integration/full-coverage
betl validate pipeline.betl.yml
betl run     pipeline.betl.yml --param batch_label=local-001
```

The `http.get` / `http.post` / `smtp.send` / `dotnet.task` stages are
gated behind `condition: ${params.enable_remote}` and skip by default —
pass `--param enable_remote=true` to exercise them (you need a reachable
SMTP server + `betl-dotnet` provider built).

## Known shape constraints

These aren't bugs in the pipeline; they're current v0.1 limitations of
the betl runtime that shaped how columns are threaded through transforms:

- `map`, `filter`, `lookup`, `sort`, `distinct`, `join`, `conditional_split`,
  `aggregate`, `pivot`, `unpivot` only accept int + utf8 input columns
  (no decimal / date / timestamp).
- `lua-expr` only emits `int64` / `utf8` / `bool` (no float64).
- `aggregate.group_by` requires int64 columns; numeric `over:` columns
  also need to be int64.
- `postgres.copy` doesn't support decimal columns (use `postgres.upsert`).

Workaround pattern used throughout: `SELECT ... ::text` on the source
side or `string.format("%.2f", ...)` in lua, then let the destination
table CAST the utf8 back to NUMERIC / DATE / TIMESTAMPTZ on insert.
