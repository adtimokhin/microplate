# AI Stack Research

Research for the deterministic Python microservice generator. Runtime target: Python 3.12, fully async (per DECISIONS.md D-004). Every AI overlay must have offline, deterministic tests using stubbed or recorded responses.

All version numbers and behaviour below were pulled from upstream sources on 2026-09-07. Each section cites the pages used with access date. Where a release date could not be read reliably from the PyPI JSON blob it is marked "date not verified"; the version string itself is corroborated across at least two fetches.

Author note on verification confidence: OpenAI, Anthropic, LangChain and MCP have all shipped new major versions since early 2026 (OpenAI 3.x, Anthropic 1.x, LangChain/LangGraph 1.x, MCP Python SDK v2). The API shapes below reflect those majors. Two items should be re-checked against the changelog before code is written: the MCP v2 server class name (`MCPServer` vs the old `FastMCP`) and the exact MCP v2 ASGI mount method name.

---

## 0. Version summary (pinned)

| Package | Latest stable | Release date | Python | Notes |
| --- | --- | --- | --- | --- |
| `openai` | 3.8.0 | 2026-09-03 | >=3.10 | Built on `httpx2`, not `httpx`. Async client `AsyncOpenAI`. |
| `anthropic` | 1.4.0 | 2026-09-04 | >=3.10 | Built on `httpx2`. Async client `AsyncAnthropic`. |
| `langchain` | 1.4.0 | 2026-09-03 | >=3.10,<4 | Meta package; pulls `langchain-core` and `langgraph`. |
| `langchain-core` | 1.6.2 | date not verified | >=3.10,<4 | Holds the fake chat models used for tests. |
| `langchain-openai` | 1.6.0 | date not verified | >=3.10,<4 | Requires `openai>=2.45,<4`. |
| `langchain-anthropic` | 1.7.1 | date not verified | >=3.10,<4 | Requires `anthropic>=0.120,<2`. |
| `langchain-qdrant` | 1.1.0 | 2025-10-22 | >=3.10,<4 | Requires `qdrant-client>=1.15.1,<2`, `langchain-core>=1.0,<2`. |
| `langgraph` | 1.2.11 | 2026-08-11 | >=3.10 | Requires `langchain-core>=1.4.7,<2`, `langgraph-checkpoint>=4.1,<5`. |
| `langgraph-checkpoint` | 4.2.0 | date not verified | >=3.10 | Base interfaces plus `InMemorySaver`. |
| `langgraph-checkpoint-postgres` | 3.1.2 | 2026-08-07 | >=3.10 | Postgres checkpointer. Requires `psycopg>=3.2`, `psycopg-pool>=3.2`, `langgraph-checkpoint>=4.1,<5`. |
| `langgraph-checkpoint-redis` | 0.5.2 | 2026-08-20 | >=3.10,<3.15 | Redis checkpointer and store. Maintained by Redis Inc. Requires `redis>=5.2.1`, `redisvl>=0.15,<1`, `langgraph-checkpoint>=4.1.1,<5`. Needs Redis 8.0+ (or Redis Stack) for RedisJSON and RediSearch modules. |
| `langsmith` | 0.12.2 | date not verified | >=3.10 | Tracing SDK. Also `httpx2`-based. |
| `mcp` | 2.2.0 (v2 line) | date not verified | >=3.10 | "v2 of the MCP Python SDK, the current stable release line." Server class is `MCPServer` (renamed from `FastMCP`); client is `mcp.Client`. |
| `qdrant-client` | 1.19.0 | date not verified | >=3.10 | Async client `AsyncQdrantClient` (all methods async since 1.6.1). |

Exact answer to the two package-name questions from the task:

- LangGraph Postgres checkpointer: PyPI package `langgraph-checkpoint-postgres`, version 3.1.2. Import path `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver` (sync variant: `from langgraph.checkpoint.postgres import PostgresSaver`).
- LangGraph Redis checkpointer: PyPI package `langgraph-checkpoint-redis`, version 0.5.2. Import path `from langgraph.checkpoint.redis.aio import AsyncRedisSaver` (sync variant: `from langgraph.checkpoint.redis import RedisSaver`). Also ships `AsyncRedisStore` / `RedisStore` for the long-term store interface.

Sources: [pypi.org/project/openai](https://pypi.org/project/openai/), [pypi.org/pypi/openai/json](https://pypi.org/pypi/openai/json), [pypi.org/project/anthropic](https://pypi.org/project/anthropic/), [pypi.org/pypi/anthropic/json](https://pypi.org/pypi/anthropic/json), [pypi.org/project/langchain](https://pypi.org/project/langchain/), [pypi.org/pypi/langchain-core/json](https://pypi.org/pypi/langchain-core/json), [pypi.org/pypi/langchain-openai/json](https://pypi.org/pypi/langchain-openai/json), [pypi.org/pypi/langchain-anthropic/json](https://pypi.org/pypi/langchain-anthropic/json), [pypi.org/pypi/langchain-qdrant/json](https://pypi.org/pypi/langchain-qdrant/json), [pypi.org/project/langgraph](https://pypi.org/project/langgraph/), [pypi.org/pypi/langgraph-checkpoint/json](https://pypi.org/pypi/langgraph-checkpoint/json), [pypi.org/project/langgraph-checkpoint-postgres](https://pypi.org/project/langgraph-checkpoint-postgres/), [pypi.org/pypi/langgraph-checkpoint-postgres/json](https://pypi.org/pypi/langgraph-checkpoint-postgres/json), [pypi.org/project/langgraph-checkpoint-redis](https://pypi.org/project/langgraph-checkpoint-redis/), [pypi.org/pypi/langgraph-checkpoint-redis/json](https://pypi.org/pypi/langgraph-checkpoint-redis/json), [pypi.org/pypi/langsmith/json](https://pypi.org/pypi/langsmith/json), [pypi.org/pypi/mcp/json](https://pypi.org/pypi/mcp/json), [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk), [pypi.org/pypi/qdrant-client/json](https://pypi.org/pypi/qdrant-client/json). All accessed 2026-09-07.

---

## 1. Cross-cutting: the `httpx2` migration and what it means for stubbing

This is the single most important offline-testing fact for the whole AI overlay set.

`openai` 3.x, `anthropic` 1.x and `langsmith` 0.12.x are all built on `httpx2` (package name `httpx2`, module `httpx2`), not the classic `httpx`. Consequences:

- `respx`, `pytest-httpx`, `vcrpy` and OpenTelemetry or Sentry `httpx` instrumentation patch the `httpx` module. They import fine but silently never see SDK traffic, because the SDK talks through `httpx2`. Tests that rely on them pass while asserting nothing.
- Two supported ways to intercept:
  1. Transport-level fake. Build `httpx2.MockTransport(handler)` where `handler` is typed `httpx2.Request -> httpx2.Response`, wrap it in the SDK's own client wrapper (`openai.DefaultAsyncHttpxClient(transport=...)` / `anthropic.DefaultAsyncHttpxClient(transport=...)`), and pass it as `http_client=`. This keeps the SDK's default timeouts and limits.
  2. Process-wide alias. Call `httpx2.alias_httpx()` before anything imports `httpx` or `httpcore` (top of the test entry point, or an early pytest plugin loaded before `respx`). After that, `import httpx` resolves to `httpx2` and the existing mocking libraries work again. Application-only, never in library import paths.
- The cleanest deterministic pattern for a generated service is neither: point the client at a local fake HTTP server via `base_url` (or the `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` env var) and run a tiny ASGI or `pytest-httpserver` app that returns canned JSON. This is transport-agnostic, exercises real serialization, and does not depend on which `httpx` the SDK uses.

Recommendation for the generator: every LLM-touching overlay should ship (a) a `conftest.py` fixture that sets `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` to a local fake and (b) a small recorded-response module. Do not generate `respx`-based tests.

Sources: `claude-api` skill bundle `python/claude-api/README.md` and `python/claude-api/sdk-upgrade.md` (Anthropic SDK v1 on `httpx2`, `httpx2.alias_httpx()`, `MockTransport` guidance), [pypi.org/pypi/openai/json](https://pypi.org/pypi/openai/json) (`httpx2<3,>=2.7.0` dependency), [github.com/openai/openai-python](https://github.com/openai/openai-python) README. Accessed 2026-09-07.

---

## 2. OpenAI Python SDK

- Version: `openai==3.8.0`, released 2026-09-03. Requires Python >=3.10. Dependencies: `anyio>=4.10,<5`, `httpx2>=2.7,<3`, `jiter>=0.16,<1`, `pydantic (<3, excludes 2.0-2.3)`, `sniffio`, `typing-extensions>=4.14,<5`. Optional extras: `aiohttp` (alternate async backend), `bedrock`, `datalib`, `realtime`, `voice-helpers`.
- Env vars: `OPENAI_API_KEY` (required), `OPENAI_BASE_URL` (base URL override, primary stubbing hook), `OPENAI_ORG_ID` / `OPENAI_PROJECT_ID` (optional), `OPENAI_LOG=debug` (SDK logging).

### Async client

```python
import os
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

async def summarize(text: str) -> str:
    resp = await client.responses.create(
        model="gpt-5.1-mini",
        instructions="Summarize the input in one sentence.",
        input=text,
        temperature=0,
    )
    return resp.output_text
```

The primary interface is the Responses API (`client.responses.create` / `.stream`). Chat Completions (`client.chat.completions.create`) is still present and supported. Embeddings live at `client.embeddings.create`.

### Timeout and retry config

- Client level: `AsyncOpenAI(timeout=20.0, max_retries=0)`. Default `timeout` is 10 minutes, default `max_retries` is 2. `timeout` accepts a float (seconds) or `httpx2.Timeout(60.0, read=5.0, write=10.0, connect=2.0)`.
- Per request: `client.with_options(timeout=5.0, max_retries=5).responses.create(...)`. Does not mutate the client.
- Retries cover connection errors, 408, 409, 429 and >=500 with exponential backoff. `max_retries=0` disables. Wall-clock worst case is `timeout * (max_retries + 1)`.

### Base URL override (stubbing)

```python
client = AsyncOpenAI(base_url="http://localhost:8085/v1")   # or set OPENAI_BASE_URL
```

For a custom transport, use `openai.DefaultAsyncHttpxClient(...)` (an `httpx2`-based wrapper) passed as `http_client=`, not a raw `httpx2.AsyncClient` and never an `httpx` client.

### Streaming (async)

```python
stream = await client.responses.create(
    model="gpt-5.1-mini",
    input="Write a haiku about determinism.",
    stream=True,
)
async for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="")
```

There is also a higher-level `async with client.responses.stream(...) as stream:` helper exposing `stream.get_final_response()`.

### Deterministic sample endpoint pattern (summarization / classification)

- Set `temperature=0` (and `top_p=1`). Note that newer reasoning-tier models ignore sampling parameters; for those, determinism comes from a fixed prompt plus the recorded-response test harness, not from the API.
- For Chat Completions, `seed=<int>` plus checking `response.system_fingerprint` gives best-effort reproducibility, but this is not a hard guarantee and should not be relied on in tests.
- Classification: constrain output with Structured Outputs (`response_format` / `text.format` with a JSON schema, `strict: true`) so the parsed result is a fixed enum. This makes assertions exact.
- The overlay's tests must not call the API. Ship a fake server (or `MockTransport`) that returns a fixed `responses.create` payload for a known input, and assert the handler's post-processing.

Sources: [github.com/openai/openai-python](https://github.com/openai/openai-python) README (async client, `with_options`, timeout, `max_retries`, `base_url`, `OPENAI_BASE_URL`, streaming), [pypi.org/pypi/openai/json](https://pypi.org/pypi/openai/json), [pypi.org/project/openai](https://pypi.org/project/openai/) (version and dates), [developers.openai.com/api/docs/guides/embeddings](https://developers.openai.com/api/docs/guides/embeddings). Accessed 2026-09-07.

---

## 3. Anthropic Python SDK

- Version: `anthropic==1.4.0`, released 2026-09-04. Requires Python >=3.10. Dependencies: `anyio>=3.5,<5`, `httpx2>=2.0,<3`, `pydantic>=1.9,<3`, `jiter>=0.4,<1`, `typing-extensions>=4.14,<5`, `docstring-parser>=0.15,<1`, `sniffio`. Extras: `bedrock`, `vertex`, `mcp`, `aiohttp`, webhook helpers.
- Env vars: `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`), `ANTHROPIC_BASE_URL` (base URL override), `ANTHROPIC_LOG=debug`.
- Current model IDs (from the bundled `claude-api` skill, cached 2026-06-24): `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5-1`. Use exact strings, no date suffixes. For a generated boilerplate default, `claude-sonnet-5` is a reasonable middle option; the overlay should expose the model as config, not hardcode it.

### Async client

```python
import anthropic

client = anthropic.AsyncAnthropic()   # reads ANTHROPIC_API_KEY

async def classify(text: str) -> str:
    msg = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=256,
        system="Reply with exactly one of: BUG, FEATURE, QUESTION.",
        messages=[{"role": "user", "content": text}],
    )
    return msg.content[0].text
```

For high-concurrency async, `pip install anthropic[aiohttp]` and pass `from anthropic import DefaultAioHttpClient` as `http_client=`.

### Timeout and retry config

- Client level: `anthropic.AsyncAnthropic(timeout=20.0, max_retries=0)`. Default `timeout` 10 minutes, default `max_retries` 2. `timeout` accepts a float (seconds) or `anthropic.Timeout(60.0, read=5.0, write=10.0, connect=2.0)` (which is `httpx2.Timeout`).
- Per request: `client.with_options(timeout=5.0, max_retries=5).messages.create(...)`.
- Auto-retries: connection errors, 408, 409, 429, >=500, exponential backoff. On timeout raises `anthropic.APITimeoutError`.

### Base URL override (stubbing)

```python
client = anthropic.AsyncAnthropic(base_url="http://localhost:8086")   # or ANTHROPIC_BASE_URL
```

Custom transport: `anthropic.DefaultAsyncHttpxClient(...)` / `anthropic.DefaultHttpxClient(...)` only, both `httpx2`-based. A client from the `httpx` package raises `TypeError` at construction.

### Streaming (async)

```python
async with client.messages.stream(
    model="claude-sonnet-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Stream a limerick."}],
) as stream:
    async for text in stream.text_stream:
        print(text, end="")
    final = await stream.get_final_message()
```

The skill guidance is to prefer `.stream()` with `.get_final_message()` for any request with large `max_tokens`.

### Tool use shape

```python
tools = [
    {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        "strict": True,   # top-level on the tool, not on tool_choice; guarantees input validates
    }
]

msg = await client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "Weather in Berlin?"}],
)
# msg.stop_reason == "tool_use"; iterate msg.content for blocks with .type == "tool_use",
# read block.name and block.input (always json.loads-safe; parse, never string-match).
# Reply with a user message containing tool_result blocks:
#   {"type": "tool_result", "tool_use_id": block.id, "content": "..."}
# Return ALL tool_result blocks for one assistant turn in a SINGLE user message.
```

Notes from the skill: forced `tool_choice` (`{"type": "any"}` / `{"type": "tool"}`) is rejected on `claude-fable-5-1`; use `{"type": "auto"}` plus an instruction, or `strict: true`, or Structured Outputs (`output_config.format`). Assistant-message prefill is removed on all current models.

### Offline test hook

Same as OpenAI: point at a fake via `ANTHROPIC_BASE_URL` or pass `anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))`. Do not use `respx` unless `httpx2.alias_httpx()` runs first. Record a fixed `messages.create` JSON body keyed by input and assert handler behaviour.

Sources: `claude-api` skill bundle `python/claude-api/README.md`, `python/claude-api/streaming.md`, `python/claude-api/tool-use.md`, `python/claude-api/sdk-upgrade.md`, `shared/model-migration.md`; [pypi.org/pypi/anthropic/json](https://pypi.org/pypi/anthropic/json); [pypi.org/project/anthropic](https://pypi.org/project/anthropic/); [github.com/anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python). Accessed 2026-09-07.

---

## 4. LangChain

- Package split (all on the 1.x line):
  - `langchain==1.4.0` (2026-09-03): meta package. Pulls `langchain-core>=1.6,<2`, `langgraph>=1.2.11,<1.3`, `pydantic>=2.7.4,<3`. Provider extras like `langchain[openai]`, `langchain[anthropic]`.
  - `langchain-core==1.6.2`: messages, runnables, prompt templates, output parsers, base chat model interface, and the fake chat models used in tests.
  - `langchain-openai==1.6.0`: `ChatOpenAI`, `OpenAIEmbeddings`. Requires `openai>=2.45,<4`, `tiktoken>=0.7,<1`.
  - `langchain-anthropic==1.7.1`: `ChatAnthropic`. Requires `anthropic>=0.120,<2`.
  - `langchain-qdrant==1.1.0` (2025-10-22): `QdrantVectorStore`. Requires `qdrant-client>=1.15.1,<2`, `langchain-core>=1.0,<2`.
- Env vars: provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are read by the provider packages. LangChain itself reads the LangSmith vars (see section 6). No LangChain-specific key is required for local use.
- Docs moved to `docs.langchain.com/oss/python/`; API reference is `reference.langchain.com/python/`.

### Prompt templates and output parsers

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_messages([
    ("system", "You classify support tickets. Output one of: BUG, FEATURE, QUESTION."),
    ("human", "{ticket}"),
])
model = ChatOpenAI(model="gpt-5.1-mini", temperature=0)
chain = prompt | model | StrOutputParser()
result = await chain.ainvoke({"ticket": "the login button does nothing"})
```

`PydanticOutputParser` (or `model.with_structured_output(MySchema)`) gives typed, assert-friendly output for classification overlays.

### Retrieval chain against Qdrant

```python
from langchain_qdrant import QdrantVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from qdrant_client import AsyncQdrantClient

emb = OpenAIEmbeddings(model="text-embedding-3-small")   # 1536 dims
store = QdrantVectorStore(
    client=AsyncQdrantClient(url="http://localhost:6333"),
    collection_name="docs",
    embedding=emb,
)
retriever = store.as_retriever(search_kwargs={"k": 4})

rag_prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer from the context only. If unknown, say so.\n\nContext:\n{context}"),
    ("human", "{question}"),
])

def format_docs(docs): return "\n\n".join(d.page_content for d in docs)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | rag_prompt | model | StrOutputParser()
)
answer = await rag_chain.ainvoke("How does checkpointing work?")
```

`langchain-qdrant` also supports dense plus sparse ("hybrid") retrieval mode via `RetrievalMode`.

### Injecting a fake LLM for tests

`langchain-core` ships the fakes. Current import paths:

```python
from langchain_core.language_models import (
    FakeListLLM,             # completion-style, cycles through a fixed list of strings
    FakeListChatModel,       # chat-style, cycles through a fixed list of responses
    FakeMessagesListChatModel,  # returns a fixed list of BaseMessage objects
    GenericFakeChatModel,    # fixed responses, also drives streaming + on_llm_new_token callbacks
)
```

`GenericFakeChatModel` is the one to use when the overlay's chain streams or exercises callbacks; it splits responses into chunks for streaming tests and works in both sync and async. Pattern: build the chain with the fake substituted for `ChatOpenAI` / `ChatAnthropic`, invoke, assert the parsed output. No network, fully deterministic.

For the retrieval chain, pair the fake chat model with an in-memory vector store (`langchain_core.vectorstores.InMemoryVectorStore`) plus a fake deterministic embedding (`langchain_core.embeddings.FakeEmbeddings` or `DeterministicFakeEmbedding`) so the retriever needs no Qdrant container in unit tests. Keep the real-Qdrant path for the testcontainers integration tier.

Sources: [pypi.org/pypi/langchain-core/json](https://pypi.org/pypi/langchain-core/json), [pypi.org/pypi/langchain-openai/json](https://pypi.org/pypi/langchain-openai/json), [pypi.org/pypi/langchain-anthropic/json](https://pypi.org/pypi/langchain-anthropic/json), [pypi.org/pypi/langchain-qdrant/json](https://pypi.org/pypi/langchain-qdrant/json), [pypi.org/project/langchain](https://pypi.org/project/langchain/), [reference.langchain.com/python/langchain-core/language_models/fake_chat_models](https://reference.langchain.com/python/langchain-core/language_models/fake_chat_models), [github.com/langchain-ai/langchain (libs/core/langchain_core/language_models/fake_chat_models.py)](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/language_models/fake_chat_models.py). Accessed 2026-09-07.

---

## 5. LangGraph

- Version: `langgraph==1.2.11`, released 2026-08-11. Requires Python >=3.10. Depends on `langchain-core>=1.4.7,<2`, `langgraph-checkpoint>=4.1,<5`, `langgraph-prebuilt>=1.1,<1.2`, `langgraph-sdk>=0.4.2,<0.5`, `pydantic>=2.7.4`, `xxhash>=3.5`.
- Checkpointer packages (this is the answer the lead asked to confirm):
  - Base plus in-memory: `langgraph-checkpoint==4.2.0`. Provides `from langgraph.checkpoint.memory import InMemorySaver` (use this in tests).
  - Postgres: package `langgraph-checkpoint-postgres==3.1.2` (released 2026-08-07). Classes `PostgresSaver` and `AsyncPostgresSaver`. Requires `psycopg>=3.2`, `psycopg-pool>=3.2`.
  - Redis: package `langgraph-checkpoint-redis==0.5.2` (released 2026-08-20, maintained by Redis Inc.). Classes `RedisSaver` / `AsyncRedisSaver` plus `RedisStore` / `AsyncRedisStore`. Requires `redis>=5.2.1`, `redisvl>=0.15,<1`, and a Redis server with the RedisJSON and RediSearch modules (Redis 8.0+ ships them by default; older servers need Redis Stack).
- Env vars: none of its own. Uses whatever DB URL the answers file selects and the LangSmith vars for tracing.

### Minimal async StateGraph

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class State(TypedDict):
    question: str
    answer: str

async def respond(state: State) -> dict:
    # real overlay calls the (stubbable) LLM client here
    return {"answer": f"echo: {state['question']}"}

builder = StateGraph(State)
builder.add_node("respond", respond)
builder.add_edge(START, "respond")
builder.add_edge("respond", END)

graph = builder.compile()   # add checkpointer=... for persistence
result = await graph.ainvoke({"question": "hi"})
```

### Async checkpointer setup

Postgres:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost:5432/app"
) as checkpointer:
    await checkpointer.setup()          # first run only: creates tables, runs migrations
    graph = builder.compile(checkpointer=checkpointer)
    await graph.ainvoke(
        {"question": "hi"},
        config={"configurable": {"thread_id": "t-1"}},
    )
```

If you pass a manually created `psycopg` connection instead of `from_conn_string`, it must be opened with `autocommit=True` and `row_factory=dict_row`.

Redis:

```python
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

async with AsyncRedisSaver.from_conn_string("redis://localhost:6379") as checkpointer:
    await checkpointer.asetup()         # note: asetup(), not setup()
    graph = builder.compile(checkpointer=checkpointer)
```

Tests: compile with `InMemorySaver()` from `langgraph-checkpoint`, substitute a fake chat model (section 4) for the node's LLM call, invoke with a fixed `thread_id`, and assert both the returned state and, if relevant, the checkpoint history via `graph.aget_state(config)`. No container needed for the unit tier. The Postgres and Redis savers get exercised in the testcontainers integration tier only.

Per DECISIONS.md D-006 the v1 overlay is one graph, one node, one route, checkpointing to Postgres or Redis per the answers file, deterministic offline tests. Multi-node loops, tool nodes, interrupts and step streaming are out of scope.

Sources: [pypi.org/project/langgraph](https://pypi.org/project/langgraph/), [pypi.org/pypi/langgraph-checkpoint/json](https://pypi.org/pypi/langgraph-checkpoint/json), [pypi.org/project/langgraph-checkpoint-postgres](https://pypi.org/project/langgraph-checkpoint-postgres/), [pypi.org/pypi/langgraph-checkpoint-postgres/json](https://pypi.org/pypi/langgraph-checkpoint-postgres/json), [pypi.org/project/langgraph-checkpoint-redis](https://pypi.org/project/langgraph-checkpoint-redis/), [github.com/redis-developer/langgraph-redis](https://github.com/redis-developer/langgraph-redis), [reference.langchain.com/python/langgraph/checkpoints](https://reference.langchain.com/python/langgraph/checkpoints), [reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver), [docs.langchain.com/oss/python/langgraph/persistence](https://docs.langchain.com/oss/python/langgraph/persistence). Accessed 2026-09-07.

---

## 6. LangSmith

- Version: `langsmith==0.12.2`. Requires Python >=3.10. Also `httpx2`-based, plus `orjson`, `zstandard`, `websockets>=15`, `requests`.
- Env vars (current `LANGSMITH_` names; legacy `LANGCHAIN_` names still honoured):
  - `LANGSMITH_TRACING=true` turns tracing on. Unset or any non-true value means tracing is off.
  - `LANGSMITH_API_KEY` authenticates ingestion.
  - `LANGSMITH_PROJECT` names the project. If unset, a default project is created on first ingest.
  - `LANGSMITH_ENDPOINT` overrides the ingest host. Required for non-US regions and useful for pointing at a local sink in tests.
  - `LANGSMITH_OTEL_ENABLED=true` optionally routes traces through OpenTelemetry instead of the native client.
- No-op behaviour: when `LANGSMITH_TRACING` (or `LANGCHAIN_TRACING_V2`) is not `true`, `@traceable` returns the wrapped function unchanged. There is zero runtime overhead and no network calls. This means the generator can leave `@traceable` decorators in generated handlers unconditionally; they cost nothing until an operator sets the env vars. LangChain and LangGraph runnables emit spans only when tracing is enabled, through the same check.

### `@traceable` decorator

```python
from langsmith import traceable

@traceable                      # span name defaults to the function name
async def retrieve(question: str) -> list[str]:
    ...

@traceable(run_type="llm", name="summarize", tags=["v1"])
async def summarize(text: str) -> str:
    ...
```

`run_type` is one of `chain`, `llm`, `tool`, `retriever`, `prompt`, `parser`. Nested `@traceable` calls form a parent-child trace tree automatically via context vars.

### Offline test hook

Two options, both simple because the decorator is inert by default:
1. Leave `LANGSMITH_TRACING` unset in the test environment (the fixture should `monkeypatch.delenv` it). Decorators become pass-throughs; assert only business behaviour.
2. If a test needs to assert that spans are produced, set `LANGSMITH_TRACING=true` and `LANGSMITH_ENDPOINT` to a local `pytest-httpserver`, or use the SDK's `langsmith.testing` utilities plus `Client(session=...)` with a mock. For this project, option 1 is sufficient for every overlay; a generated service should never require a LangSmith endpoint to pass its tests.

Sources: [pypi.org/pypi/langsmith/json](https://pypi.org/pypi/langsmith/json), [docs.langchain.com/langsmith/observability-quickstart](https://docs.langchain.com/langsmith/observability-quickstart), [docs.langchain.com/langsmith/trace-without-env-vars](https://docs.langchain.com/langsmith/trace-without-env-vars), [reference.langchain.com/python/langsmith/run_helpers/traceable](https://reference.langchain.com/python/langsmith/run_helpers/traceable), [github.com/langchain-ai/langsmith-sdk](https://github.com/langchain-ai/langsmith-sdk). Accessed 2026-09-07.

---

## 7. MCP (Model Context Protocol) Python SDK

- Version: `mcp==2.2.0`, described upstream as "v2 of the MCP Python SDK, the current stable release line." Requires Python >=3.10. Dependencies include `httpx2>=2.5`, `pydantic>=2.12`, `starlette`, `uvicorn>=0.31`, `jsonschema>=4.20`, `opentelemetry-api>=1.28`. Install `pip install "mcp[cli]"` for the `mcp` command-line tool, plain `pip install mcp` otherwise.
- Breaking change from the v1 line: the quick-server class is now `MCPServer` imported from `mcp.server` (it was `FastMCP` from `mcp.server.fastmcp` in v1). The client is now `mcp.Client`. Verify these names against the v2 changelog before the overlay is coded, since this is a recent rename and much existing material still shows `FastMCP`.
- Transports: stdio, Streamable HTTP, and SSE. Streamable HTTP is the deployment transport; stdio is for local subprocess use and the inspector.
- Env vars: none mandated by the SDK. The generated MCP overlay would take host/port and an auth token from the service's own settings loader.

### Minimal server scaffold

```python
# server.py
from mcp.server import MCPServer

mcp = MCPServer("my-service")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()   # stdio by default
```

Type hints are the schema. `a: int, b: int` is the input schema; no JSON Schema is written by hand.

### Running with a transport

- stdio (default): `mcp.run()` in code, or `uv run mcp dev server.py` for the inspector.
- Streamable HTTP: `uv run mcp run server.py --transport streamable-http` (serves on `/mcp`).

### Wrapping existing FastAPI endpoints

Two paths, in order of preference for this project:

1. Thin re-export. In the MCP overlay module, `import` the service's existing async handler functions (the same functions the FastAPI routes call) and register each as an `@mcp.tool()`. The tool body calls the shared service-layer function directly, so REST and MCP share one implementation and one set of tests. This matches DECISIONS.md D-007, where the tool scaffold and the MCP overlay are separate registry keys over the same endpoints.
2. Mount the MCP ASGI app into the FastAPI app so both are served from one process:

```python
from fastapi import FastAPI
from .mcp_server import mcp   # the MCPServer instance

api = FastAPI(lifespan=mcp.streamable_http_app().lifespan)  # pass MCP lifespan through
api.mount("/mcp", mcp.streamable_http_app())
```

The exact method name for getting the ASGI app from an `MCPServer` in v2 needs a changelog check: community material shows `streamable_http_app()` and also a newer `http_app(transport="streamable-http")`. Whichever it is, it returns a Starlette app that `FastAPI.mount` accepts, and its lifespan must be chained into the parent app or sessions will not initialise.

### Offline test hook

MCP servers are tested in-process with no transport. Use the SDK's in-memory client-server pair (client connected directly to the server object, no stdio or HTTP), call `client.call_tool("add", {"a": 1, "b": 2})`, and assert `result.structured_content`. Because each tool body just calls a shared service function, most coverage comes from the plain unit tests of that function; the MCP test only needs to prove the tool is registered and its schema is right. Fully deterministic, no network.

Sources: [pypi.org/pypi/mcp/json](https://pypi.org/pypi/mcp/json), [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk), [py.sdk.modelcontextprotocol.io](https://py.sdk.modelcontextprotocol.io/), [github.com/modelcontextprotocol/python-sdk issue #1367 (FastAPI mount)](https://github.com/modelcontextprotocol/python-sdk/issues/1367), [deepwiki.com/modelcontextprotocol/python-sdk/9.1-running-servers](https://deepwiki.com/modelcontextprotocol/python-sdk/9.1-running-servers). Accessed 2026-09-07.

---

## 8. Embedding client and the Qdrant ingestion job

### Embedding models

- OpenAI, current recommended models (via `client.embeddings.create` or `OpenAIEmbeddings`):
  - `text-embedding-3-small`: default 1536 dimensions. Cheapest, good baseline for RAG.
  - `text-embedding-3-large`: default 3072 dimensions. Higher quality.
  - Both: max 8192 input tokens per item.
  - `dimensions` request parameter truncates the output vector (Matryoshka-style) without destroying its meaning, for example `dimensions=256` or `512` to cut storage and speed search. If you set it, the Qdrant collection must be created with the same size.
- Local option worth noting: `fastembed` (from the Qdrant team, an optional extra of `qdrant-client` as `qdrant-client[fastembed]`). Runs ONNX models on CPU, no API key, fully offline. Default model `BAAI/bge-small-en-v1.5` at 384 dimensions. This is the natural choice for the generator's own deterministic tests and for services that must not call OpenAI. `langchain-qdrant` also integrates fastembed for sparse vectors in hybrid mode.
- Determinism: a given model plus input yields a stable vector, so recorded embedding fixtures are reliable. For unit tests of the ingestion job, use `DeterministicFakeEmbedding` (LangChain) or a recorded `fastembed` vector rather than calling OpenAI.

### Vector dimensions to configure in Qdrant

Match the collection's `size` to the embedding: 1536 for `text-embedding-3-small`, 3072 for `text-embedding-3-large`, 384 for the default fastembed model, or whatever `dimensions` was set to. Distance metric `Cosine` (OpenAI vectors are unit-normalised, so cosine and dot product rank identically).

### Batching for an ingestion job into Qdrant

- Embedding side: send inputs to `embeddings.create` in arrays. Keep each request under the token ceiling and under a few hundred items; 96 to 256 texts per request is a safe range. Await requests concurrently with a bounded `asyncio.Semaphore` (4 to 8 in flight) to keep throughput up without hitting rate limits.
- Qdrant write side (`AsyncQdrantClient`, all methods async since client 1.6.1):
  - Under ~100k points: a single-threaded loop of batched `upsert` calls, 64 to 256 points per batch.
  - 100k to 1M points: `upload_points` with `batch_size` 1000 to 10000 and `parallel=2..4`.
  - Over 1M points: `upload_collection` to stream from disk.
- The generated ingestion job should: read source docs, chunk, embed in bounded-concurrency batches, then `upsert`/`upload_points` in batches of ~128, with retry/backoff on the Qdrant call. Expose batch size and concurrency as settings. Ship a collection-bootstrap step that creates the collection with the correct `size` and `Cosine` distance if absent.
- Offline test: fake the embedding call (deterministic fake or recorded vectors) and run Qdrant either in-memory (`AsyncQdrantClient(":memory:")`, supported by the Python client) for unit tests or via testcontainers for the integration tier. Assert collection point count and a known-vector search result.

Sources: [developers.openai.com/api/docs/guides/embeddings](https://developers.openai.com/api/docs/guides/embeddings), [pypi.org/pypi/qdrant-client/json](https://pypi.org/pypi/qdrant-client/json), [github.com/qdrant/qdrant-client](https://github.com/qdrant/qdrant-client), [qdrant.tech/documentation/tutorials-develop/bulk-upload](https://qdrant.tech/documentation/tutorials-develop/bulk-upload/), [qdrant.tech/course/essentials/day-4/large-scale-ingestion](https://qdrant.tech/course/essentials/day-4/large-scale-ingestion/), [python-client.qdrant.tech/qdrant_client.async_qdrant_client](https://python-client.qdrant.tech/qdrant_client.async_qdrant_client). Accessed 2026-09-07.

---

## 9. Implications for the registry and overlays

- Every LLM overlay needs a `*_BASE_URL` env var wired into its settings loader so tests and local dev can redirect to a fake. Make this a first-class registry-generated setting, not an afterthought.
- Do not generate `respx` / `pytest-httpx` tests for the OpenAI, Anthropic or LangSmith overlays. Generate either local-fake-server fixtures or `httpx2.MockTransport` fixtures.
- Pin exact versions in the generated `pyproject.toml`. Suggested pins as of 2026-09-07: `openai==3.8.0`, `anthropic==1.4.0`, `langchain==1.4.0`, `langchain-core==1.6.2`, `langchain-openai==1.6.0`, `langchain-anthropic==1.7.1`, `langchain-qdrant==1.1.0`, `langgraph==1.2.11`, `langgraph-checkpoint-postgres==3.1.2`, `langgraph-checkpoint-redis==0.5.2`, `langsmith==0.12.2`, `mcp==2.2.0`, `qdrant-client==1.19.0`.
- Python 3.12 target is safe for all of the above (every package allows >=3.10; `langgraph-checkpoint-redis` caps at <3.15).
- LangGraph checkpointer selection maps to two registry values that pull different packages: `postgres` -> `langgraph-checkpoint-postgres`, `redis` -> `langgraph-checkpoint-redis`. The Redis path additionally requires the target Redis to have RedisJSON and RediSearch (Redis 8.0+ image, or `redis/redis-stack`), which the generated docker-compose must reflect.
- The MCP overlay depends on the tool scaffold or gRPC (D-007). Its cleanest form is re-exporting shared service-layer functions as `@mcp.tool()`; mounting the MCP ASGI app into FastAPI is the alternative when one process must serve both.
- Embedding overlay should offer both an OpenAI embedding client and an offline `fastembed` client, so a service (and the generator's own tests) can run with no external API.
