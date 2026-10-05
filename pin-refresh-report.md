# Pin refresh report - 2026-10-05

| Package | Current | Latest stable | Status | Locations |
| --- | --- | --- | --- | --- |
| aio-pika | 10.0.1 | 10.1.0 | OUTDATED | registry.yaml:options.messaging_rabbitmq |
| alembic | 1.19.2 | 1.20.0 | OUTDATED | registry.yaml:options.db_postgres |
| anthropic | 1.4.0 | 1.11.0 | OUTDATED | registry.yaml:options.llm_anthropic |
| anyio | 4.11.0 | 4.15.1 | OUTDATED | registry.yaml:options.tests_unit |
| asyncpg | 0.31.0 | 0.31.0 | current | registry.yaml:options.db_postgres |
| copier | 9.18.2 | 9.18.2 | current | pyproject.toml:[project].dependencies |
| greenlet | 3.5.5 | 3.5.6 | OUTDATED | registry.yaml:options.db_postgres |
| grpcio | 1.83.1 | 1.84.0 | OUTDATED | registry.yaml:options.api_grpc |
| grpcio-health-checking | 1.83.1 | 1.84.0 | OUTDATED | registry.yaml:options.api_grpc |
| grpcio-reflection | 1.83.1 | 1.84.0 | OUTDATED | registry.yaml:options.api_grpc |
| grpcio-status | 1.83.1 | 1.84.0 | OUTDATED | registry.yaml:options.api_grpc |
| grpcio-tools | 1.83.1 | 1.84.0 | OUTDATED | registry.yaml:options.api_grpc |
| langchain | 1.4.0 | 1.4.3 | OUTDATED | registry.yaml:options.langchain |
| langchain-anthropic | 1.7.1 | 1.7.5 | OUTDATED | registry.yaml:options.langchain |
| langchain-core | 1.6.2 | 1.6.6 | OUTDATED | registry.yaml:options.langchain |
| langchain-openai | 1.6.0 | 1.6.7 | OUTDATED | registry.yaml:options.langchain |
| langchain-qdrant | 1.1.0 | 1.1.0 | current | registry.yaml:options.langchain |
| langgraph | 1.2.11 | 1.2.12 | OUTDATED | registry.yaml:options.langgraph |
| langgraph-checkpoint | 4.2.0 | 4.2.0 | current | registry.yaml:options.langgraph |
| langgraph-checkpoint-postgres | 3.1.2 | 3.1.2 | current | registry.yaml:options.langgraph |
| langgraph-checkpoint-redis | 0.5.2 | 0.5.2 | current | registry.yaml:options.langgraph |
| langsmith | 0.12.2 | 0.14.4 | OUTDATED | registry.yaml:options.langsmith |
| mcp | 2.2.0 | 2.3.0 | OUTDATED | registry.yaml:options.mcp_server |
| mypy | 2.3.1 | 2.4.0 | OUTDATED | pyproject.toml:[dependency-groups].dev |
| openai | 3.8.0 | 3.24.0 | OUTDATED | registry.yaml:options.llm_openai |
| opentelemetry-exporter-otlp-proto-http | 1.44.0 | 1.45.0 | OUTDATED | registry.yaml:options.otel_tracing |
| opentelemetry-instrumentation-fastapi | 0.65b0 | 0.66b0 | OUTDATED | registry.yaml:options.otel_tracing |
| opentelemetry-sdk | 1.44.0 | 1.45.0 | OUTDATED | registry.yaml:options.otel_tracing |
| packaging | 26.3 | 26.3 | current | pyproject.toml:[dependency-groups].dev |
| protobuf | 7.36.1 | 7.36.2 | OUTDATED | registry.yaml:options.api_grpc |
| psycopg | 3.3.5 | 3.3.6 | OUTDATED | registry.yaml:options.langgraph |
| psycopg-pool | 3.3.1 | 3.3.3 | OUTDATED | registry.yaml:options.langgraph |
| pymongo | 4.18.0 | 4.18.2 | OUTDATED | registry.yaml:options.db_mongodb |
| pytest | 9.1.1 | 9.1.1 | current | registry.yaml:options.tests_unit, pyproject.toml:[dependency-groups].dev |
| pytest-asyncio | 1.4.0 | 1.4.0 | current | registry.yaml:options.tests_unit, pyproject.toml:[dependency-groups].dev |
| pytest-cov | 7.1.0 | 7.1.0 | current | registry.yaml:options.tests_unit |
| pyyaml | 6.0.2 | 6.0.3 | OUTDATED | pyproject.toml:[project].dependencies |
| qdrant-client | 1.19.0 | 1.19.1 | OUTDATED | registry.yaml:options.db_qdrant |
| qdrant-client[fastembed] | 1.19.0 | 1.19.1 | OUTDATED | registry.yaml:options.embedding_pipeline |
| redis | 8.1.0 | 8.1.0 | current | registry.yaml:options.db_redis |
| ruff | 0.16.6 | 0.16.10 | OUTDATED | pyproject.toml:[dependency-groups].dev |
| sqlalchemy[asyncio] | 2.0.52 | 2.1.3 | OUTDATED | registry.yaml:options.db_postgres |
| sse-starlette | 3.4.11 | 3.5.0 | OUTDATED | registry.yaml:options.streaming_sse |
| structlog | 26.1.0 | 26.1.0 | current | registry.yaml:options.logging_structured |
| tenacity | 9.1.4 | 9.1.4 | current | registry.yaml:options.llm_openai, registry.yaml:options.llm_anthropic |
| testcontainers | 4.15.0 | 4.15.0 | current | registry.yaml:options.tests_integration |
| testcontainers[rabbitmq] | 4.15.0 | 4.15.0 | current | registry.yaml:options.messaging_rabbitmq |
| types-pyyaml | 6.0.12.20250915 | 6.0.12.20260906 | OUTDATED | pyproject.toml:[dependency-groups].dev |

Compose image pins (D-023, Data Layer Engineer) are NOT checked here yet - TODO.

Per D-019: review each bump against the upstream changelog before merging this PR.
