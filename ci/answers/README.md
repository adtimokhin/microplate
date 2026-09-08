# ci/answers/

Fixed answers files rendered by the determinism job (`scripts/check_determinism.py`)
and, later, by the Testing Engineer's pairwise harness. Each file is a complete,
valid answers set (scope §6): every question that lacks a default must be present.

Add one file per combination worth guarding. Keep them small and named for the
combo: `zero-overlay.yml`, `postgres-only.yml`, `postgres-rabbitmq.yml`, ...

Until the base template lands these are inert; the determinism job skips when
there is no `copier.yml` at the repo root.
