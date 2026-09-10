# embedding_pipeline

An embedding client plus a batched ingestion job that writes vectors into the
Qdrant collection bootstrapped by the `db_qdrant` overlay.

## Keys
- `embedding_pipeline` (bool) - the overlay. Requires `db_qdrant` (V-4).
- `embedding_backend` (`fastembed` default | `openai`, `when: embedding_pipeline`).
  `openai` requires `llm_openai` (V-8). `fastembed` is offline via the
  `qdrant-client[fastembed]` extra - no key, deterministic (D-014).
- `embedding_vector_size` (`when: embedding_pipeline`) - feeds `APP_QDRANT_VECTOR_SIZE`
  so the collection dimension matches the backend (fastembed 384, openai 1536).

## Determinism / tests
Offline. The autouse `embedding_client` fixture patches `embed_texts` to fixed
zero vectors and `expected_dim` to the configured size; the boots test patches
`ensure_collection` / `upsert`. No model download, no Qdrant server, no OpenAI
call.

## Files
- `{{ python_package }}/embeddings/embedder.py` - fastembed / openai backends
- `{{ python_package }}/embeddings/ingest.py` - `ingest_documents(...)`, batched, upserts to Qdrant
