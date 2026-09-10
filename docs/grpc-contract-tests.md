# gRPC contract test approach

Spec only. The Messaging & Topology Engineer builds this in Phase 3 (milestone
6), gated on `tests_contract` (which itself requires `topology != 'single'` and
`transport_grpc`, rule V-11).

Source research: `research/messaging-grpc.md`, "Contract testing options for gRPC
in Python". Decisions D-009 (committed stubs + pinned regen + CI diff guard).

## What a gRPC contract test protects

That a `.proto` change does not silently break a wire-compatible or
source-compatible consumer. In this generator that means: within a `monorepo` or
across `multi_repo` services that talk gRPC, the shared `proto/` definitions stay
backward compatible as the template and the generated services evolve.

It is schema-level. It does not verify runtime behavior between a specific
consumer and provider (that is Pact, listed as an optional overlay below, not the
default).

## Default: `buf breaking` + `buf lint`

Ship a `buf.yaml` and a CI job in the generated project when `tests_contract` is
selected.

- `buf lint` enforces proto style (package naming, file layout, enum and field
  conventions) so generated protos stay consistent.
- `buf breaking --against '.git#branch=main'` (or against the last release tag)
  fails CI when a proto change is wire-breaking or source-breaking: removed or
  renumbered fields, changed field types, removed RPCs or services, changed
  cardinality.

Properties:

- `buf` is a single Go binary, language-agnostic, does not run the Python
  service. Install from the released binary or the `bufbuild/buf` container
  image, pinned to an exact version in the generated CI workflow.
- Fits the boilerplate: vendor `buf.yaml` (+ `buf.gen.yaml` if buf also drives
  codegen, though D-009 keeps codegen on pinned `grpc_tools.protoc`), add one CI
  job. No change to the service runtime or its dependency set.
- Catches syntactic and wire breakage only. It will not catch a semantic change
  that keeps the schema compatible.

CI job shape (generated project, `tests_contract` selected):

```yaml
proto-contract:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with: { fetch-depth: 0 }
    - uses: bufbuild/buf-setup-action@v1
      with: { version: "<pinned>" }
    - run: buf lint
    - run: buf breaking --against ".git#branch=main"
```

## No-toolchain fallback: FileDescriptorSet snapshot diff

For teams that will not add the `buf` binary to CI.

- Generate a descriptor set with the already-pinned toolchain:
  `python -m grpc_tools.protoc -I proto --descriptor_set_out=proto/descriptor.pb --include_imports <every .proto in fixed order>`.
- Commit `proto/descriptor.pb` (or a canonical text form via
  `protoc --decode_raw` / a small normalizer for a readable diff).
- CI regenerates it and runs `git diff --exit-code proto/descriptor.pb`. Any
  proto change that alters the descriptor set fails until the snapshot is
  updated in the same PR, forcing a human to look at the change.

Properties: deterministic, no extra runtime dependency, reuses the D-009 pinned
`grpcio-tools` / `protobuf`. Weaker than `buf`: it flags every change, breaking
or not, so it is a review prompt rather than a breaking-change classifier.

This pairs naturally with the D-009 committed-stub CI guard
(`regenerate, then git diff --exit-code` on the `_pb2*.py` files): same
mechanism, one more artifact.

## Optional overlay (not default): pact-python + protobuf plugin

Consumer-driven behavioral contracts. `pact-python==3.4.0` (FFI-based) plus the
out-of-band `pactflow/pact-protobuf-plugin`. Verifies actual request/response
semantics between a named consumer and provider. Adds a plugin binary and a pact
broker (or PactFlow). Reasonable as its own opt-in registry key for teams that
need it; too heavy to be the default gRPC contract safeguard.

## Recommendation

1. Default when `tests_contract` is selected: `buf lint` + `buf breaking` CI job,
   `buf` version pinned in the generated workflow.
2. Document the descriptor-set snapshot fallback in the generated project's
   README for teams that cannot add `buf`.
3. Leave pact-python as a future opt-in overlay (`BACKLOG.md`), not v1.

## Harness integration (Phase 3)

- `harness/run.py` gains a `contract` step that runs when the combination has
  `tests_contract == true`: it invokes the generated project's `buf` job locally
  (`buf lint` + `buf breaking` against a synthetic prior revision) or the
  descriptor-set diff, and records pass / fail per combination like every other
  step.
- The synthetic prior revision for `buf breaking` in the harness: render the same
  answers file at the previous template tag, take its `proto/`, and diff forward.
  This reuses the `copier update` machinery the DevOps engineer already has.
