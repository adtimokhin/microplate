# Overlay: topology (multi-service: `monorepo` / `multi_repo`)

Multi-service output is produced by **orchestration in the generator**, not one
giant Copier render (D-036, supersedes the single-run `{% yield %}` mechanism in
D-017). N ordinary `single`-style renders in frozen `service_names` order + one
thin root wiring layer.

- Owner: TopologyEngineer
- Registry keys: `topology` (`single` | `monorepo` | `multi_repo`, default
  `single`), `service_names` (yaml list), `services_config` (json map),
  `transport_grpc` (bool), `transport_rabbitmq` (bool), `tests_contract` (bool)
- Overlay ids: `transport_grpc`, `transport_rabbitmq` (in `overlay_order`)
- Milestone: 6 (Phase 3)
- Decisions: D-005, D-009, D-012, D-016, D-017 (`services_config` intent),
  **D-036** (mechanism), D-020 (transport split), D-027 / D-032 (fragment slots)
- Schema: `docs/services-config-schema.md`
- Contract-test spec: `docs/grpc-contract-tests.md`

## Mechanism (D-036)

`cli.py` calls `msvc_gen/topology.py` **only** when `topology != 'single'`. The
`single` path in `cli.py` is untouched and its output is byte-identical to
before this overlay existed (verified).

1. **Per-service render.** For each name in `service_names` (frozen order),
   `topology.py` runs a normal `single`-style `copier.run_copy` driven by that
   service's *effective answer set*:

   ```
   registry defaults
     <- shared top-level keys (license, ci, iac, docker, topology,
        service_names, transport_grpc, transport_rabbitmq)
     <- services_config[<svc>] submap
     <- forced identity: service_name = <svc>
        (Copier derives service_slug = <svc>, python_package = <svc>|replace('-','_'))
     <- services_config = {}   (not recursive; keeps the per-service answers lean)
     <- tests_contract = false (contract tests are a root-layer job)
   ```

   `monorepo` -> `services/<svc>/`; `multi_repo` -> `<output>/<svc>/`. **One code
   path, different destination.** Each service directory keeps its **own**
   `.copier-answers.yml` (Copier's native per-run model), so a plain
   `copier update` inside one service works, and per-service update granularity
   falls out for free.

2. **Root wiring layer.** `topology.py` then renders
   `msvc_gen/root_templates/<topology>/` with a plain Jinja env (no Copier, no
   overlay fragments - it carries no user business logic and is re-rendered
   wholesale on update):

   | File | When | Content |
   | --- | --- | --- |
   | `.copier-answers.yml` | always | MANIFEST: `topology`, `service_name` (repo name), `service_names`, `services_config`, shared keys. `msvc-gen update --output .` re-drives every service render from this. |
   | `docker-compose.yml` | always | one app container per service (build context into each service dir), wired to reach peers by service name; `depends_on` + a namespaced-once backing service per datastore/broker any submap selects (images read from `registry.yaml` `compose_services`); shared `rabbitmq` when `transport_rabbitmq`. |
   | `README.md` | always | roster table, transport summary, run/test/update instructions. |
   | `.github/workflows/ci.yml` | always | matrix over the service dirs (`uv sync --locked` / `ruff` / `mypy` / `pytest` each); `proto-contract` job when `tests_contract`. |
   | `proto/example/v1/example.proto` | `transport_grpc` or any `api_grpc` service | the canonical **shared** inter-service contract. |
   | `buf.yaml` | `tests_contract` | buf v2 config: `lint` STANDARD, `breaking` FILE, module `proto`. |
   | `proto/gen_descriptor_set.py` | `tests_contract` | the no-toolchain fallback (FileDescriptorSet snapshot) from `docs/grpc-contract-tests.md`. |

3. **`copier update` (monorepo)** = `copier.run_update` per `services/<svc>/` +
   re-render the root layer. The roster / submaps come from the root manifest,
   not re-discovered from disk.

## Validation

`topology.py._prepare` runs fast structural checks (roster non-empty, name regex,
no duplicate / package-collision, submap keys in the per-service allow-list) and
then delegates the authoritative replay to
`scripts/validate_registry.validate_services_config` (V-15..V-20 + per-service
replay of V-2..V-14). The generator **rejects**, it never guesses (scope §6). A
`monorepo`/`multi_repo` generation with an invalid `services_config` exits
non-zero with the failing rule messages before any render.

## Transport wiring - the design choice (task item 3)

**Shared contracts live at the root; generated client code lives in each service
tree.** Concretely:

- **Root layer**: the shared `proto/` tree + `buf.yaml` (the wire contract every
  service in a `transport_grpc` mesh agrees on). One `buf lint` + `buf breaking`
  job in the root CI (`tests_contract`).
- **Per-service** (rendered by Copier into each service, gated on the shared
  `transport_grpc` / `transport_rabbitmq` answers passed through to every
  service):

  | Overlay | Gated subtree | Fragments |
  | --- | --- | --- |
  | `transport_grpc` | `{{ python_package }}/transport/grpc/` - `peers.py` (`PEERS` tuple from `service_names`; `peer_target()` resolves `APP_PEER_<NAME>_GRPC_TARGET`, default `<peer-slug>:50051`; `peer_channel()` async ctx mgr) | `settings.py` (`peer_<pkg>_grpc_target` per peer), `env.example` (`APP_PEER_<NAME>_GRPC_TARGET`), `deps.toml` (`grpcio`, `grpcio-status` `==1.83.1`) |
  | `transport_rabbitmq` | `{{ python_package }}/transport/rabbitmq/` - `bus.py` (`connect` / `publish` / `consume` over one shared durable topic exchange; `inbox_queue_name()` = `<service_name>.inbox`) | `settings.py` (`transport_rabbitmq_url`, `transport_exchange`, `transport_rabbitmq_prefetch`), `env.example`, `deps.toml` (`aio-pika==10.0.1`), `compose.yml` + `compose.app-deps.yml` (adds a `rabbitmq` service + `depends_on` to the service's **standalone** compose, but only `{% if not messaging_rabbitmq %}` so it never duplicates that overlay's broker) |

  Each also ships `tests/overlays/test_transport_<x>_boots.py` (offline: no socket
  opened; asserts the peer registry / bus surface and settings wiring).

Rationale: `transport_grpc` / `transport_rabbitmq` are **shared** (§2.1 of the
schema) - the whole mesh must agree on how peers talk - so the transport overlay
renders in *every* service as the client side. A service exposes its *own* gRPC
server only if its submap sets `api_grpc` (per-service); `transport_grpc` does
not force it (V-18/V-T4 guarantees at least one `api_grpc` service in the mesh).
Keeping the contract at the root and the client code per-service means: one
place to change the wire schema, `buf breaking` guards it for everyone, and each
service still builds / tests / type-checks in isolation exactly like a `single`
service.

## `tests_contract` (gRPC contract tests)

`when: topology != 'single'`, `requires: transport_grpc` (V-11). Runs in the
**root** CI, never per-service (`effective_answers` forces `tests_contract=false`
into every per-service render).

- **Default**: `buf lint` + `buf breaking --against ".git#branch=main"`, buf
  version pinned in the workflow. (The pin is currently a literal `1.47.2` with
  a `TODO(registry)` - flagged to RegistryArchitect to add a `buf` tool pin to
  `registry.yaml`.)
- **No-toolchain fallback**: `proto/gen_descriptor_set.py` regenerates a
  canonical `FileDescriptorSet` with the already-pinned `grpcio-tools` /
  `protobuf` (D-009); CI runs it + `git diff --exit-code proto/descriptor.pb`.
  Shipped as a commented-out job block in the root workflow.
- **Harness** (`docs/grpc-contract-tests.md` §"Harness integration"): a
  `contract` step for combinations with `tests_contract == true` - render the
  same answers at the previous template tag, take its `proto/`, diff forward.

## Determinism

- Services processed in `service_names` list order (frozen; reordering needs a
  migration per overlay-contract §8.2).
- Effective submap = pure dict merge over a fixed key list.
- Root context: union of backing services in `service_names` order then a fixed
  overlay-key order; `services_config` serialized with `sort_keys=True`.
- Verified: `single` byte-identical to pre-overlay baseline; `monorepo` and
  `multi_repo` 2-service renders byte-identical across two runs
  (`.copier-answers.yml` `_commit` / `_src_path` normalized - Copier mints a
  throwaway snapshot commit per dirty-worktree render, stable under a pinned
  `--vcs-ref`).

## Files

```
msvc_gen/topology.py                 orchestration (cli.py dispatches here iff topology != single)
msvc_gen/root_templates/monorepo/    root wiring layer for monorepo
msvc_gen/root_templates/multi_repo/  root wiring layer for multi_repo
template/{% if transport_grpc %}{{ python_package }}{% endif %}/transport/grpc/
template/{% if transport_rabbitmq %}{{ python_package }}{% endif %}/transport/rabbitmq/
template/{% if transport_grpc %}tests{% endif %}/overlays/test_transport_grpc_boots.py.jinja
template/{% if transport_rabbitmq %}tests{% endif %}/overlays/test_transport_rabbitmq_boots.py.jinja
template/_fragments/transport_grpc/       settings.py, env.example, deps.toml
template/_fragments/transport_rabbitmq/   settings.py, env.example, deps.toml, compose.yml, compose.app-deps.yml
docs/services-config-schema.md       submap schema (integrated by RegistryArchitect)
```

## Not done / follow-ups

- `buf` version is a literal pin in the root workflow; wants a `registry.yaml`
  tool pin (flagged to RegistryArchitect).
- Root shared `proto/example/v1/example.proto` and the `api_grpc` overlay's own
  `proto/example/v1/example.proto` have identical message/service definitions
  but different leading comments; converging them on one source is a cleanup.
- Live multi-service boots test (`docker compose up --wait` + inter-service
  call): see the TopologyEngineer report for the run result.

## Phase 7 addendum: harness wiring

`harness/run.py` now orchestrates `topology != single` combinations for real
(`msvc_gen.topology.run_multi_service_new`, per-service + root-layer checks)
instead of rendering a single degenerate tree, and `tests_contract` runs real
`buf lint` (skip-safe) + the descriptor-set fallback against the rendered root
`proto/`. Details: `harness/README.md` "`topology != single` orchestration"
and "`tests_contract` real wiring". `docs/grpc-contract-tests.md` records what
is and is not wired (no synthetic-prior-revision `buf breaking` yet - no
tagged prior revision exists to diff against).
