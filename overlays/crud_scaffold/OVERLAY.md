# crud_scaffold

Initial data-access code so a generated service is not just a bare datastore
client: an example entity, an async repository, and REST CRUD endpoints.

## Keys
- `crud_scaffold` (bool). Requires `db_postgres or db_mongodb or db_redis`.
- `crud_entity` (str, default `item`) - the example entity name. Class =
  capitalized (`Item`), table/collection/route prefix = `<entity>s` (`/items`).
- `crud_backend` (computed) - the datastore it binds to, by priority
  `db_postgres` > `db_mongodb` > `db_redis`.

## What it ships (`{{ python_package }}/data/`)
- `models.py` - `<Entity>Create` / `<Entity>Update` / `<Entity>` pydantic models{% raw %} + (postgres) a SQLAlchemy `<Entity>Row` table{% endraw %}.
- `repository.py` - async repo with `create`, `get`, `list` (limit/offset),
  `update` (partial), `delete`, `count`, `exists`; the backend implementation
  plus `InMemory<Entity>Repository` for offline tests.
- `routes.py` - `POST/GET/PATCH/DELETE /<entity>s`, `GET /<entity>s/{id}`,
  `GET /<entity>s/count`, wired via the `api_router` slot.

## Determinism / tests
Offline. The autouse `crud_repository` fixture swaps `get_repository` for
`InMemory<Entity>Repository`. No datastore needed. Postgres backend: run
`alembic revision --autogenerate` after generation to create the `<entity>s`
table for real use.
