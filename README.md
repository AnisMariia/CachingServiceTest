# Caching service

FastAPI microservice that builds payloads from two lists of strings and caches
the results of a slow "transformer" so each distinct string is transformed once.

* `POST /payload` with `{"list_1": [...], "list_2": [...]}` (equal length) → `201 {"id": "<uuid>"}` for a new payload, `200` with the same id if an identical one already exists
* `GET /payload/{id}` → `{"output": "..."}` (`404` if unknown)

The transformer (`transformer.py`) upper-cases a string after a simulated delay.
The output is the transformed strings interleaved and joined with `", "`.

## How caching works

* `cached_transformations` stores one row per distinct source string, keyed by its
  SHA-256 (a B-tree index cannot hold arbitrarily long text). A request looks up all
  of its strings in a single query and calls the transformer only for the misses.
* `payloads` stores the finished output with a unique hash of it, so an identical
  payload always gets the same id, and `GET` never touches the transformer.

## Concurrency

The service is fully async (async endpoints, SQLAlchemy `AsyncSession`, async transformer).

* **No duplicate calls:** concurrent requests that need the same uncached string share a
  single transformer call (`TransformerPool`). That call is shielded from cancellation, so a
  client disconnecting does not fail the other requests waiting on it.
* **Bounded load:** `TRANSFORMER_CONCURRENCY` (default 10) caps simultaneous transformer calls.
* **No idle connections:** the DB connection is released before the slow transformer calls.
* **Race-free writes:** rows are inserted with `ON CONFLICT DO NOTHING`, and the payload id is
  read back, so concurrent identical requests always agree on one id and one row. Cache rows
  are inserted sorted by hash, so overlapping requests lock rows in the same order and cannot
  deadlock.

## Run

```sh
docker compose up --build        # applies migrations, then serves on http://localhost:8000
```

Without Docker (needs a PostgreSQL; set `DATABASE_URL` or put it in `.env`):

```sh
uv sync
uv run alembic upgrade head
uv run uvicorn caching_service.app:app
```

## CLI

```sh
uv run cache-cli -j '{"list_1": ["a", "b"], "list_2": ["c", "d"]}' -r 3
uv run cache-cli -i payload.json -o result.json
cat payload.json | uv run cache-cli -i -
```

Options: `-H/--host URL`, `-r/--repeat N`, `-i/--input FILE|-`, `-j/--json JSON`,
`-o/--output FILE|-`, `-h/--help`.

Assumptions about the CLI spec:

* **`-h` conflict.** The spec lists `-h` for both `--host` and `--help`, which argparse cannot
  allow. `-h` stays `--help`; the host short flag is `-H`.
* **Input.** Exactly one of `--input` and `--json` is required (giving both or neither is an
  error). `--input -` reads stdin. The body has the same shape and limits as the API request.
* **Host.** Defaults to `http://127.0.0.1:8000`; must start with `http://` or `https://`;
  a trailing `/` is ignored.
* **Repeat.** `--repeat N` (N >= 1, default 1) repeats the POST + GET sequentially with the same
  body, so repeated runs show the cache at work (same id each time).
* **Output.** A JSON list with one `{"id": ..., "output": ...}` per iteration, written to stdout,
  or to the file given by `--output` (overwritten if it exists).
* **Errors.** Invalid arguments or input, unreadable files and HTTP/network failures print one
  message to stderr and exit non-zero; nothing is written to the output in that case.
  Requests time out after 30 s.

## Tests

```sh
uv run pytest        # needs Docker
```

Linting and types (Python 3.12+):

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests migrations
```

Tests run against a throwaway PostgreSQL started with testcontainers, with the schema built
by the real Alembic migrations, so the SQL and the migrations are exercised as in production.

## Known shortcuts

* Sharing of in-flight transformer calls works per process. With several replicas, the same
  string may be transformed once per replica at most at the same moment; the database still
  keeps a single row and a single payload id.
* The CLI stays synchronous: it is a sequential test tool, so async would add nothing.
