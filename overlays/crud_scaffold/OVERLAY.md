# crud_scaffold

Initial data-access code so a generated service is not just a bare datastore
client: an example entity, an async repository, and REST CRUD endpoints.

## Keys
- `crud_scaffold` (bool). Requires `db_postgres or db_mongodb or db_redis`.
- `crud_entity` (str, default `item`) - the example entity name. Class =
  capitalized (`Item`), table/collection/route prefix = `<entity>s` (`/items`).
- `crud_backend` (computed) - the datastore it binds to, by priority
  `db_postgres` > `db_mongodb` > `db_redis`.
- `crud_soft_delete` (bool, default `false`, `when: crud_scaffold`, D-042) -
  `delete`/`bulk_delete` set `deleted_at` instead of removing the row/doc/hash;
  `get`/`list`/`count`/`exists`/`update` then treat that entity as not found.
  Default `false` is behavior-identical to before D-042 (hard delete).

## What it ships (`{{ python_package }}/data/`)
- `models.py` - `<Entity>Create` / `<Entity>Update` / `<Entity>` pydantic
  models{% raw %} + (postgres) a SQLAlchemy `<Entity>Row` table (gains a
  nullable `deleted_at` column when `crud_soft_delete`){% endraw %};
  `<Entity>ListResponse` (`items` + `total`) and `<Entity>BulkDeleteRequest`
  (`ids: list[str]`).
- `repository.py` - async repo Protocol: `create`, `bulk_create`, `get`,
  `list` (limit/offset/`name_contains`), `update` (partial), `delete`,
  `bulk_delete`, `count` (optional `name_contains`), `exists`; one backend
  implementation (Postgres batched insert/update/delete via SQLAlchemy Core,
  Mongo `insert_many`/`update_many`/`delete_many`, Redis pipelined
  create + client-side name filter - no secondary index) plus
  `InMemory<Entity>Repository` for offline tests.
- `routes.py` - `POST/GET/PATCH/DELETE /<entity>s`, `GET /<entity>s/{id}`,
  `GET /<entity>s/count`, `POST /<entity>s/bulk` (bulk create, body is a JSON
  array of create payloads), `POST /<entity>s/bulk-delete` (body
  `{"ids": [...]}`, returns `{"deleted": N}`), all wired via the `api_router`
  slot. `GET /<entity>s` returns `{"items": [...], "total": N}` (the total
  respects the `name_contains` filter, not just the base dataset).

## Determinism / tests
Offline. The autouse `crud_repository` fixture swaps `get_repository` for
`InMemory<Entity>Repository` - this is the ONLY repository pytest ever
exercises, in every configuration (mock or `tests_integration`), so the
boots test's assertions hold identically whether `crud_backend` is postgres,
mongodb, or redis, and whether `crud_soft_delete` is on or off (a
soft-deleted row disappears from `get`/`list`/`count` exactly like a hard
delete does - the difference is invisible to a black-box HTTP client, only
internal storage differs). Postgres backend: run
`alembic revision --autogenerate` after generation to create the
`<entity>s` table (and the `deleted_at` column, if `crud_soft_delete`) for
real use.
