# Overlay: messaging_rabbitmq

RabbitMQ publisher/consumer scaffolding for the async FastAPI service.

- Owner: MessagingEngineer
- Registry key: `messaging_rabbitmq` (bool, default `false`)
- Overlay id: `messaging_rabbitmq`
- Milestone: 3 (Phase 2)
- Decisions: D-004 (aio-pika, async), D-027 (`compose.app-deps` slot), D-019 (pins)
- Research: `research/messaging-grpc.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/messaging/` - `client.py` (`RabbitMQ`: robust connection + two channels, publisher confirms, bounded-prefetch consumer, `set_connection_factory` test seam), `topology.py` (`TopologyConfig` + `declare_topology`: events exchange, DLX, work queue, TTL retry queue, terminal dead queue), `consumer.py` (`consume_with_retry` + `delivery_attempts`: x-death attempt count, nack->DLX retry cycle, park on the dead queue after `max_attempts` or a `PermanentError`) |
| `pyproject.toml` | `aio-pika==10.0.1` |
| `config/settings.py` | `rabbitmq_url`, `rabbitmq_prefetch` |
| `.env.example` | `APP_RABBITMQ_URL`, `APP_RABBITMQ_PREFETCH` |
| `lifespan.py` | startup hook (open robust connection, declare topology, put `RabbitMQ` on `app.state.rabbitmq`, register the health holder), shutdown hook (close connection, clear holder) |
| `health.py` | `check_messaging_rabbitmq()` - zero-arg, reads the lifespan-set holder, opens and closes a channel to prove the broker answers |
| `docker-compose.yml` | `rabbitmq` service (`rabbitmq:4.1-management`, healthcheck `rabbitmq-diagnostics -q ping`) |
| `docker-compose.yml` `app.depends_on` | `rabbitmq: {condition: service_healthy}` via `compose.app-deps.yml` (D-027) |
| `tests/conftest.py` | `rabbitmq_channel` (mock: installs a fake robust connection, no socket), `rabbitmq_container` (testcontainers, only rendered when `tests_integration`) |
| Boots test | `tests/overlays/test_messaging_rabbitmq_boots.py` |

## Design notes

- `connect_robust` + `RobustChannel` always, so channels/queues/consumers/QoS
  recover after a network blip (`research/messaging-grpc.md`).
- Publisher confirms are on by default at the channel level; `publish` uses
  `mandatory=True` and raises `DeliveryError` on a nack.
- Retry is the portable DLX + TTL delayed-retry topology (no broker plugin). A
  message cycles work queue -> DLX -> retry queue (`x-message-ttl`) -> work queue
  until `delivery_attempts` (read from `x-death`) reaches `max_attempts`, then it
  is published to the terminal dead queue and acked so it stops cycling.
- `set_connection_factory` is the only test seam. The mock fixture swaps in a
  fake so `uv run pytest` is fully offline; the boots test still enters the real
  lifespan and calls the real health check.
- No CI fragment: `tests_integration` uses testcontainers, which manages its own
  containers and needs no workflow change.
