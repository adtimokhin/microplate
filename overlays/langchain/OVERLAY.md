# langchain

LangChain integration: a chat-model factory that selects the configured provider
(OpenAI or Anthropic), a sample `prompt | model | parser` summarize chain behind
`POST /langchain/summarize`, and an optional retrieval chain.

## Keys
- `langchain` (bool) - the overlay.
- `langchain_retrieval` (bool, `when: langchain`) - adds a Qdrant retrieval chain
  behind `POST /langchain/retrieve`. Requires `db_qdrant` (V-6).

## Requires
- `llm_openai or llm_anthropic` (V-7). Provider packages (`langchain-openai`,
  `langchain-anthropic`) are added to `pyproject.toml` conditionally on which LLM
  overlay is selected; `langchain-qdrant` only when `langchain_retrieval`.

## Determinism / tests
Offline. The autouse `langchain_llm` fixture patches `chain.build_chat_model` to
return `FakeListChatModel` (D-013). No provider key or network needed. The
retrieval chain's `_retrieve` is patched to a fixed document list in the boots
test.

## Files
- `{{ python_package }}/langchain/chain.py` - model factory + summarize chain
- `{{ python_package }}/langchain/routes.py` - the endpoints, wired via the `api_router` slot
- `{{ python_package }}/langchain/retrieval.py` - retrieval chain (content only when `langchain_retrieval`)
