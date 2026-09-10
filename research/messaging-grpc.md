# Messaging and gRPC Research

Runtime target: Python 3.12, fully async. All findings pulled from current upstream
sources on 2026-09-07. Versions reflect the latest stable releases on PyPI as of that date.

## Version summary

| Package | Latest stable | Released | requires_python | Key deps |
|---|---|---|---|---|
| aio-pika | 10.0.1 | 2026-07-09 | >=3.11,<4 | aiormq >=7,<8; yarl |
| aiormq (transport under aio-pika) | 7.0.0 | 2026-07-09 | >=3.11,<4 | pamqp >=4,<5; yarl |
| grpcio | 1.83.1 | 2026-08-28 | >=3.10 | typing-extensions ~=4.12 |
| grpcio-tools | 1.83.1 | 2026-08-28 | >=3.10 | protobuf >=7.35.1,<8; grpcio >=1.83.1; setuptools >=77.0.1 |
| protobuf (Python runtime) | 7.36.1 | 2026-08-31 | >=3.10 | none |
| grpcio-health-checking | 1.83.1 | 2026-08-28 | >=3.10 | protobuf >=7.35.1,<8; grpcio >=1.83.1 |
| grpcio-reflection | 1.83.1 | 2026-08-28 | >=3.10 | protobuf >=7.35.1,<8; grpcio >=1.83.1 |
| grpcio-status | 1.83.1 | 2026-08-28 | >=3.10 | protobuf >=6.33.5,<8; grpcio >=1.83.1; googleapis-common-protos >=1.5.5 |
| pact-python | 3.4.0 | 2026-05-04 | >=3.10 | pact-python-ffi ~=0.5.0 |

Notes:
- Keep the grpc* family pinned to one identical version across grpcio, grpcio-tools,
  grpcio-health-checking, grpcio-reflection, grpcio-status. They release in lockstep.
- protobuf 7.36.1 satisfies the `>=7.35.1,<8` constraint of grpcio-tools 1.83.1. Pin
  protobuf explicitly in the lockfile so codegen output stays byte-stable.
- Python 3.12 wheel availability is confirmed for grpcio 1.83.1 and grpcio-tools 1.83.1:
  `cp312` wheels are published for macOS (universal2), manylinux2014 (x86_64, aarch64,
  i686, armv7l), and musllinux_1_2 (x86_64, aarch64, i686), plus win32/win_amd64. No
  source build is needed on any mainstream CI runner or container base image.
- aio-pika 10.0.1 is pure Python (`py3-none-any` wheel); aiormq 7.0.0 is also pure
  Python. No native build. Minimum Python is 3.11, so 3.12 is fine.

---

## RabbitMQ overlay (aio-pika)

### Robust connection

Use `aio_pika.connect_robust(...)` (returns a `RobustConnection`). It provides
"transparent auto-reconnects with full state recovery": on reconnect it re-opens
channels and re-declares the exchanges, queues, bindings, and consumers that were
created through the aio-pika objects, and it restores the QoS/prefetch settings and
re-registers consumer callbacks. Publisher-confirm channel mode is also restored.

```python
import aio_pika

connection = await aio_pika.connect_robust(
    "amqp://guest:guest@rabbitmq:5672/",
    client_properties={"connection_name": "orders-service"},
)
# reconnect cadence is controlled by the `reconnect_interval` kwarg (seconds,
# default 5). `connect_robust` also accepts `timeout`, `fail_fast`, and the
# same URL/kwargs as `connect`.
channel = await connection.channel()          # RobustChannel
await channel.set_qos(prefetch_count=16)      # restored after reconnect
```

Always create the connection and channel through the robust variants. A plain
`connect()` / `Connection` will not recover and will surface `ConnectionClosed` to
the caller on network loss.

### Publisher confirms

Publisher confirms are enabled by default at the channel level
(`connection.channel(publisher_confirms=True)`). With confirms on, `await
exchange.publish(...)` waits for the broker ack and returns the confirmation frame;
a broker nack raises `aio_pika.exceptions.DeliveryError`, and a missing confirm
within `timeout` raises `asyncio.TimeoutError`.

```python
from aio_pika import Message, DeliveryError
from pamqp.commands import Basic

async def publish(channel, routing_key: str, body: bytes) -> None:
    exchange = await channel.declare_exchange("app.events", "topic", durable=True)
    try:
        confirm = await exchange.publish(
            Message(
                body,
                content_type="application/json",
                delivery_mode=2,            # persistent
                message_id=str(uuid4()),
            ),
            routing_key=routing_key,
            mandatory=True,                 # broker returns unroutable messages
            timeout=5.0,
        )
    except DeliveryError:
        # broker nacked the publish; treat as a hard failure
        raise
    except asyncio.TimeoutError:
        raise
    if not isinstance(confirm, Basic.Ack):
        raise RuntimeError("publish not acked by broker")
```

For unroutable messages, set `mandatory=True`. Channel kwarg `on_return_raises=True`
turns a returned (unroutable) message into an exception on the `publish` awaitable
instead of a background return callback.

### Consumer with prefetch and manual ack

```python
async def consume(connection) -> None:
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=16)     # bounded in-flight per consumer

    queue = await channel.declare_queue(
        "orders.process",
        durable=True,
        arguments={
            "x-dead-letter-exchange": "orders.dlx",
            "x-dead-letter-routing-key": "orders.process.failed",
        },
    )

    async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            await handle(message.body)
        except TransientError:
            # negative ack, no requeue -> routed to the DLX (see retry pattern)
            await message.nack(requeue=False)
        except PermanentError:
            await message.reject(requeue=False)
        else:
            await message.ack()

    await queue.consume(on_message)               # manual ack (no_ack=False default)
    await asyncio.Future()                        # run forever
```

`async with message.process():` is the context-manager alternative: it acks on clean
exit and nacks (configurable requeue) on exception. For explicit retry routing,
prefer manual `ack` / `nack(requeue=False)` / `reject(requeue=False)` so you control
whether a message is dead-lettered or dropped.

### Dead-letter queue setup (DLX / DLQ via queue arguments)

A dead-letter exchange is an ordinary exchange. A message is dead-lettered when any
of these occur on its queue:

1. consumer `basic.reject` or `basic.nack` with `requeue=false`;
2. per-message or per-queue TTL expiry;
3. queue length limit (`x-max-length` / `x-max-length-bytes`) exceeded;
4. quorum-queue delivery-limit exceeded.

Declare the work queue with `x-dead-letter-exchange` (and optionally
`x-dead-letter-routing-key`, which defaults to the message's original routing key):

```python
dlx = await channel.declare_exchange("orders.dlx", "topic", durable=True)
dlq = await channel.declare_queue("orders.process.dead", durable=True)
await dlq.bind(dlx, routing_key="orders.process.failed")

work = await channel.declare_queue(
    "orders.process",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "orders.dlx",
        "x-dead-letter-routing-key": "orders.process.failed",
    },
)
```

RabbitMQ upstream recommends setting DLX via a policy rather than queue arguments in
production, because policies can be changed without deleting and re-declaring the
queue. The generator can emit both: arguments for the self-contained dev compose
file, and a commented `rabbitmqctl set_policy` example for ops.

### Retry / backoff for consumers

`aio-pika` has no dedicated retry documentation and ships no retry helper. The
current recommended approach for RabbitMQ is the DLX + TTL delayed-retry topology,
implemented with queue arguments:

- Work queue `orders.process` dead-letters to `orders.dlx` with routing key
  `...retry`.
- A wait queue `orders.process.retry` is bound to `orders.dlx` for that key, has
  `x-message-ttl` set to the desired backoff (for example 30000 ms), and its own
  `x-dead-letter-exchange` pointing back to the exchange that feeds
  `orders.process`. When the TTL expires the message is dead-lettered again, this
  time back onto the work queue.
- On each delivery the consumer reads an attempt counter from
  `message.headers["x-death"]` (RabbitMQ appends one entry per dead-letter event) or
  from a custom `x-retry-count` header it maintains. After N attempts it publishes
  to a terminal `orders.process.dead` DLQ and acks, so the message stops cycling.
- For staged backoff (for example 10s, 1m, 5m) declare several wait queues with
  different TTLs and route to the next one based on the attempt count.

```
publish -> [ex: app.events] -> orders.process --(nack requeue=false)--> [orders.dlx]
  [orders.dlx routing "retry"] -> orders.process.retry (x-message-ttl=30s,
       x-dead-letter-exchange=app.events, x-dead-letter-routing-key=orders.process)
  --TTL expiry--> app.events -> orders.process   (attempt + 1)
  after max attempts: publish -> [orders.dlx routing "dead"] -> orders.process.dead
```

Alternative: the community plugin `rabbitmq_delayed_message_exchange` gives a single
`x-delayed-message` exchange and per-message `x-delay` header, removing the wait-queue
sprawl, but it is a broker plugin (not core) so it must be installed in the image. For
a boilerplate that must run against a stock broker, the DLX + TTL topology is the
portable default. Library-level retry (for example `tenacity`) should only wrap the
in-handler business call for fast transient faults; it must not be used to sleep while
holding an unacked delivery, because that blocks a prefetch slot and risks consumer
timeout.

### Health check contribution

The overlay's health hook should report the AMQP connection state, which aio-pika
exposes directly:

```python
async def rabbitmq_health(connection: aio_pika.abc.AbstractRobustConnection) -> bool:
    # `is_closed` is False while the robust connection is up or actively recovering
    return connection is not None and not connection.is_closed
```

For a stricter check, open a temporary channel and declare a passive (exclusive,
auto-delete) queue, or call `channel.declare_queue(passive=True)` on a known queue;
this proves the broker is reachable and responsive, not just that the socket object
exists. Keep the strict check on the readiness probe and the cheap `is_closed` check
on liveness so a transient reconnect does not restart the pod.

### Minimal publisher + consumer for an overlay

```python
# messaging/rabbitmq.py
import asyncio
import aio_pika
from aio_pika import Message, DeliveryError

class RabbitMQ:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None

    async def start(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=16)

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.close()

    async def publish(self, exchange: str, routing_key: str, body: bytes) -> None:
        ex = await self._channel.declare_exchange(
            exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )
        try:
            await ex.publish(
                Message(body, content_type="application/json", delivery_mode=2),
                routing_key=routing_key,
                mandatory=True,
                timeout=5.0,
            )
        except (DeliveryError, asyncio.TimeoutError):
            raise

    async def consume(self, queue_name: str, handler) -> None:
        queue = await self._channel.declare_queue(
            queue_name,
            durable=True,
            arguments={"x-dead-letter-exchange": f"{queue_name}.dlx"},
        )
        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            try:
                await handler(message.body)
            except Exception:
                await message.nack(requeue=False)   # -> DLX
            else:
                await message.ack()
        await queue.consume(on_message)

    def healthy(self) -> bool:
        return self._connection is not None and not self._connection.is_closed
```

---

## gRPC overlay

### Versions and Python 3.12 wheels

grpcio 1.83.1, grpcio-tools 1.83.1, protobuf 7.36.1. All ship prebuilt cp312 wheels
for Linux (manylinux2014 and musllinux_1_2, x86_64 + aarch64), macOS universal2, and
Windows. grpcio-health-checking, grpcio-reflection, and grpcio-status are also at
1.83.1 and are pure-Python. Pin all five grpc packages to the exact same version and
pin protobuf.

### Async API (grpc.aio) server and client

Server:

```python
import asyncio
import grpc
from app.gen import greeter_pb2, greeter_pb2_grpc

class Greeter(greeter_pb2_grpc.GreeterServicer):
    async def SayHello(
        self,
        request: greeter_pb2.HelloRequest,
        context: grpc.aio.ServicerContext,
    ) -> greeter_pb2.HelloReply:
        return greeter_pb2.HelloReply(message=f"Hello, {request.name}!")

async def serve() -> None:
    server = grpc.aio.server()
    greeter_pb2_grpc.add_GreeterServicer_to_server(Greeter(), server)
    server.add_insecure_port("[::]:50051")
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5.0)   # drain in-flight RPCs for up to 5s

if __name__ == "__main__":
    asyncio.run(serve())
```

Client:

```python
import grpc
from app.gen import greeter_pb2, greeter_pb2_grpc

async def run() -> None:
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = greeter_pb2_grpc.GreeterStub(channel)
        response = await stub.SayHello(greeter_pb2.HelloRequest(name="world"))
        print(response.message)
```

Key `grpc.aio` surface: `grpc.aio.server(interceptors=..., options=...)`;
`Server.add_insecure_port` / `add_secure_port(addr, server_credentials)`;
`await server.start()`; `await server.stop(grace)`;
`await server.wait_for_termination(timeout=None)`.
Channels: `grpc.aio.insecure_channel(target, options, compression, interceptors)` and
`grpc.aio.secure_channel(...)`, both usable as `async with`. Server-side
`grpc.aio.ServicerContext` offers `await context.read()`, `await context.write(msg)`,
`await context.abort(code, details)`, `context.set_code()`, `context.set_details()`,
`await context.send_initial_metadata(...)`. Interceptors: `ServerInterceptor`
(`intercept_service`) and the four client interceptor base classes
(`UnaryUnaryClientInterceptor`, `UnaryStreamClientInterceptor`,
`StreamUnaryClientInterceptor`, `StreamStreamClientInterceptor`).

### Proto layout, stub generation, commit vs generate

Recommended layout in a generated project:

```
proto/
  app/v1/greeter.proto            # source of truth, hand-written
src/app/gen/
  __init__.py
  app/v1/greeter_pb2.py           # generated
  app/v1/greeter_pb2.pyi          # generated (type stubs)
  app/v1/greeter_pb2_grpc.py      # generated
```

Generation command (async client/server stubs are included in `greeter_pb2_grpc.py`
by default in current grpcio-tools; no separate flag needed):

```
python -m grpc_tools.protoc \
  -I proto \
  --python_out=src/app/gen \
  --pyi_out=src/app/gen \
  --grpc_python_out=src/app/gen \
  proto/app/v1/greeter.proto
```

One caveat with `grpc_python_out`: generated `_pb2_grpc.py` uses
`import app.v1.greeter_pb2` style absolute imports rooted at the `-I` dir. Put the
`-I` root and the `--*_out` root so that the import path matches the package the code
is installed under (as above, both resolve to `app.v1...` under `src/app/gen`), or
post-process with a tool like `protoletariat` to rewrite imports to relative.

Recommendation on commit vs generate, given the determinism requirement: **commit the
generated `_pb2.py`, `_pb2.pyi`, and `_pb2_grpc.py` into the generated project, and
also emit a `make proto` / script target that regenerates them.** Rationale:

- Determinism of the emitted project is judged at generation time. If stubs are
  generated at build time, the project's build now depends on the exact
  grpcio-tools + protobuf + libprotoc versions on every machine and in CI; a patch
  bump to protoc changes the bytes of the output and breaks reproducibility for
  downstream users who did not change their proto.
- Committed stubs make the repo runnable and testable immediately after generation
  with no protoc toolchain present, which matches the boilerplate's "clone and run"
  goal.
- The regeneration script plus a CI check (`regenerate, then git diff --exit-code`)
  keeps the committed stubs honest and pins the toolchain version in the project's
  own lockfile, so the drift is caught in the generated project's CI rather than
  silently at each user's build.
- The generator itself must run protoc with a pinned grpcio-tools/protobuf and a
  fixed `-I` ordering and file ordering so the committed output is identical across
  runs. Do not include absolute paths in the command (protoc can embed the given
  path in comments/imports); always pass repo-relative paths.

### Server-streaming and bidi-streaming minimal example

```proto
service Feed {
  rpc Subscribe (SubReq) returns (stream Event);       // server streaming
  rpc Chat (stream ChatMsg) returns (stream ChatMsg);  // bidirectional
}
```

```python
class Feed(feed_pb2_grpc.FeedServicer):
    async def Subscribe(self, request, context: grpc.aio.ServicerContext):
        async for event in produce_events(request.topic):
            yield feed_pb2.Event(payload=event)          # server streaming: yield

    async def Chat(self, request_iterator, context: grpc.aio.ServicerContext):
        async for msg in request_iterator:               # read client stream
            yield feed_pb2.ChatMsg(text=msg.text.upper())  # write response stream
```

```python
# client: server-streaming
async with grpc.aio.insecure_channel("localhost:50051") as channel:
    stub = feed_pb2_grpc.FeedStub(channel)
    call = stub.Subscribe(feed_pb2.SubReq(topic="orders"))
    async for event in call:
        print(event.payload)

# client: bidi
async def outgoing():
    for i in range(3):
        yield feed_pb2.ChatMsg(text=f"msg {i}")
call = stub.Chat(outgoing())
async for reply in call:
    print(reply.text)
```

### Health checking (grpc_health.v1)

Use the standard gRPC Health Checking Protocol via `grpcio-health-checking`. The
async servicer is `grpc_health.v1.health.aio.HealthServicer` (implemented in
`grpc_health/v1/_async.py`). Wire it into the same `grpc.aio` server:

```python
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_health.v1.health import aio as health_aio

health_servicer = health_aio.HealthServicer()
health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

# overall server status uses the empty string key
await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
# per-service granularity
await health_servicer.set(
    "app.v1.Greeter", health_pb2.HealthCheckResponse.SERVING
)
```

The async `HealthServicer` supports `Check` (unary) and `Watch` (server-streaming
status updates), tracks status per service name in an internal map guarded by an
`asyncio.Condition`, and has `enter_graceful_shutdown()` which flips every service to
`NOT_SERVING` and freezes further `set()` calls, for clean drain on shutdown. Toggle
a dependency's key (for example set the DB-backed service to `NOT_SERVING`) from the
same health hooks used for the HTTP `/healthz` so external probes see a single
consistent status. The generic client probe is `grpc_health_probe` (Go binary,
common in Kubernetes) or `grpc.health.v1.Health/Check` from any stub. Pair with
`grpcio-reflection` (`reflection.enable_server_reflection`) so `grpcurl` and probes
can discover services without local protos.

### Contract testing options for gRPC in Python (current state)

- **buf (`buf breaking`, `buf lint`)**: the current standard for schema-level
  contract safety. `buf breaking --against '.git#branch=main'` detects
  wire/source-breaking proto changes in CI. It is a Go CLI (install via released
  binary or `buf` Docker image), language-agnostic, and does not run the Python
  service. Best fit for a boilerplate: vendor a `buf.yaml` + `buf.gen.yaml` and a CI
  job. This catches syntactic breakage only.
- **Schema snapshot / descriptor diff**: cheap DIY alternative when adding the buf
  toolchain is unwanted. Emit a `FileDescriptorSet` with
  `protoc --descriptor_set_out=proto.pb --include_imports` and diff it (or a
  canonical text form) against the committed snapshot in CI. Deterministic, no extra
  runtime dep, weaker rule set than buf.
- **pact-python 3.4.0 + Pact Protobuf/gRPC plugin**: consumer-driven,
  behaviour-level contract testing. pact-python v3 is FFI-based
  (`pact-python-ffi ~=0.5.0`); gRPC/protobuf support comes from the separate
  `pactflow/pact-protobuf-plugin` (a Pact v4 plugin, installed out-of-band) which
  matches and verifies protobuf messages and gRPC calls. This is the option that
  verifies request/response semantics between a specific consumer and provider, but
  it adds a plugin binary, a broker (or PactFlow) for sharing pacts, and notably
  more setup than buf. Reasonable as an opt-in overlay, not a default.

Recommendation: ship **buf breaking + buf lint in CI as the default** gRPC contract
safeguard (with a descriptor-set snapshot fallback documented), and offer
**pact-python + the protobuf plugin as an optional overlay** for teams that need
consumer-driven behavioural contracts.

---

## Recommendations back to the team

1. **aio-pika 10.0.1**. Always use `connect_robust` + `RobustChannel`. Publisher
   confirms on by default; treat `DeliveryError` / `TimeoutError` as hard failures.
   Consumer: `set_qos(prefetch_count=N)` + manual ack. Retry via the DLX + TTL
   delayed-retry topology built from queue arguments (no library helper exists;
   aio-pika has no retry docs). Health hook: `not connection.is_closed` for
   liveness, passive queue declare for readiness.
2. **grpcio / grpcio-tools / protobuf = 1.83.1 / 1.83.1 / 7.36.1**, all with cp312
   wheels, no native build on standard runners. Pin the whole grpc* family to one
   version.
3. **gRPC stubs: commit the generated `_pb2.py` / `_pb2.pyi` / `_pb2_grpc.py` into
   the generated project AND provide a pinned regeneration script plus a CI
   `git diff --exit-code` guard.** Committing wins for determinism because build-time
   generation makes every downstream build depend on the exact local protoc/protobuf
   version; the CI regen check prevents the committed copy from drifting. The
   generator must invoke protoc with pinned tool versions, repo-relative paths, and
   fixed input ordering so its own output is reproducible.
4. Health: standard `grpc_health.v1` via `grpcio-health-checking`, async
   `health.aio.HealthServicer`, `set("", SERVING)` for overall plus per-service
   keys, `enter_graceful_shutdown()` on stop. Add `grpcio-reflection` for probe/CLI
   discovery.
5. Contract testing: buf (`buf breaking` + `buf lint`) in CI as default, descriptor
   set snapshot as the no-toolchain fallback, pact-python 3.4.0 + pact-protobuf-plugin
   as an optional behavioural-contract overlay.

---

## Sources

All accessed 2026-09-07.

- aio-pika PyPI metadata (version 10.0.1, deps, requires_python): https://pypi.org/pypi/aio-pika/json
- aiormq PyPI metadata (7.0.0): https://pypi.org/pypi/aiormq/json
- aio-pika documentation home (robust connection, auto-reconnect with state recovery): https://docs.aio-pika.com/
- aio-pika patterns and helpers (Master/Worker, RPC, RejectMessage/NackMessage): https://docs.aio-pika.com/patterns.html
- aio-pika work queues tutorial (`channel.set_qos(prefetch_count=...)`, `message.process()`, `queue.consume`, `declare_queue(durable=True)`): https://docs.aio-pika.com/rabbitmq-tutorial/2-work-queues.html
- aio-pika publisher confirms tutorial (`publisher_confirms=True` default, `DeliveryError`, `on_return_raises`, `mandatory`): https://docs.aio-pika.com/rabbitmq-tutorial/7-publisher-confirms.html
- aio-pika API reference (Connection/RobustConnection, Channel, Message/IncomingMessage ack/reject/process, exceptions): https://docs.aio-pika.com/apidoc.html
- RabbitMQ dead letter exchanges (x-dead-letter-exchange, x-dead-letter-routing-key, four dead-letter triggers, DLX+TTL retry pattern, policy vs argument guidance): https://www.rabbitmq.com/docs/dlx
- grpcio PyPI metadata (1.83.1, cp312 wheels, requires_python >=3.10): https://pypi.org/pypi/grpcio/json
- grpcio 1.83.1 release files (cp312 manylinux/musllinux/macos/win wheels): https://pypi.org/pypi/grpcio/1.83.1/json
- grpcio-tools PyPI metadata (1.83.1, protobuf >=7.35.1,<8, cp312 wheels): https://pypi.org/pypi/grpcio-tools/json
- protobuf PyPI metadata (7.36.1, released 2026-08-31): https://pypi.org/pypi/protobuf/json
- grpcio-health-checking PyPI metadata (1.83.1): https://pypi.org/pypi/grpcio-health-checking/json
- grpcio-reflection PyPI metadata (1.83.1): https://pypi.org/pypi/grpcio-reflection/json
- grpcio-status PyPI metadata (1.83.1): https://pypi.org/pypi/grpcio-status/json
- pact-python PyPI metadata (3.4.0, FFI-based, pact-python-ffi ~=0.5.0): https://pypi.org/pypi/pact-python/json
- gRPC Python quickstart (install commands, `python -m grpc_tools.protoc` with `--python_out --pyi_out --grpc_python_out`): https://grpc.io/docs/languages/python/quickstart/
- gRPC Python basics tutorial (server-streaming via `yield`, bidi via request iterator + yield): https://grpc.io/docs/languages/python/basics/
- gRPC async greeter server example (`grpc.aio.server()`, `add_insecure_port`, `await server.start()`, `wait_for_termination`): https://github.com/grpc/grpc/blob/master/examples/python/helloworld/async_greeter_server.py
- gRPC async greeter client example (`async with grpc.aio.insecure_channel(...)`, `await stub.SayHello(...)`): https://github.com/grpc/grpc/blob/master/examples/python/helloworld/async_greeter_client.py
- gRPC AsyncIO API reference (server/channel/ServicerContext/interceptor surface): https://grpc.github.io/grpc/python/grpc_asyncio.html
- gRPC async health servicer source (`grpc_health.v1._async.HealthServicer`, set/Check/Watch, enter_graceful_shutdown): https://github.com/grpc/grpc/blob/master/src/python/grpcio_health_checking/grpc_health/v1/_async.py
- gRPC health servicer reference implementation (`grpc_health/v1/health.py`): https://github.com/grpc/grpc/blob/master/src/python/grpcio_health_checking/grpc_health/v1/health.py
- gRPC xDS example server (health.HealthServicer + add_HealthServicer_to_server + health_servicer.set(...) + reflection.enable_server_reflection): https://github.com/grpc/grpc/blob/master/examples/python/xds/server.py
- buf breaking-change detection and buf + Pact complementary pattern for gRPC/protobuf: https://pactflow.io/blog/contract-testing-for-grpc-and-protobufs/
- Pact Protobuf/gRPC plugin (Pact v4 plugin for protobuf messages and gRPC service calls): https://github.com/pactflow/pact-protobuf-plugin
