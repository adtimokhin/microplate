# langgraph

A minimal stateful LangGraph graph behind one route, checkpointed to the
selected store (D-006). Off by default. This is the only place agent-style
control flow appears in a generated service.

## Keys
- `langgraph` (bool). Requires `db_postgres or db_redis` (V-5).
- `langgraph_checkpoint` (`postgres` default | `redis`, `when: langgraph`). The
  chosen store must be enabled (V-9). Postgres uses `AsyncPostgresSaver` over
  psycopg3 (separate from the `db_postgres` asyncpg engine); Redis uses
  `AsyncRedisSaver` and the compose redis service is auto-upgraded to
  redis-stack (image_resolution IR-1, D-015).

## Graph
`prepare -> respond`, state = `{messages, turn}`. `respond` is deterministic text
work; swap it for an LLM node (`llm_openai` / `langchain`) for a real step.
`POST /langgraph/run` invokes one turn; reuse `thread_id` to resume from the
checkpoint.

## Determinism / tests
Offline. The autouse `langgraph_app` fixture patches `build_checkpointer` to an
`InMemorySaver`. No DB, no LLM call. Multi-node agent loops, tool nodes, HITL
interrupts, and step streaming are BACKLOG.

## Files
- `{{ python_package }}/langgraph/graph.py` - the StateGraph + nodes
- `{{ python_package }}/langgraph/checkpointer.py` - store-specific saver
- `{{ python_package }}/langgraph/routes.py` - `POST /langgraph/run`
