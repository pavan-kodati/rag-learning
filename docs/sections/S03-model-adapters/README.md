# S03 · Model adapters (all open source, all local)

## 1. Spec

**Goal:** isolate every model dependency behind three small ports (LLM, embedder, reranker) so the product runs on a
laptop with **zero cost** (Ollama + open-weight models) and moves to vLLM/TEI on GPU nodes by changing configuration only
(blueprint ADR-03, §12). Add the resilience an enterprise deployment needs.

**My call (you asked me to decide):**

| Role | Local default (free) | Production option (same code) |
| ---- | -------------------- | ----------------------------- |
| Main LLM (extraction, answers, brief) | `qwen3:8b` via **Ollama** (Apache-2.0); `qwen3:4b` on small machines | Qwen3-8B on **vLLM** (`LLM_PROVIDER=openai_compat`) |
| Fast LLM (router, classifier) | `qwen3:4b` | Qwen3-4B on vLLM |
| Embeddings | `bge-m3` via Ollama (MIT, 1024-d) | BGE-M3 on TEI |
| Reranker | none by default; `bge-reranker-v2-m3` via sentence-transformers (`RERANKER=cross_encoder`) | TEI `/rerank` |
| Demo / CI | `fixture` LLM + `hashing` embedder: no model download at all | n/a |

Why Ollama locally: one binary, runs on CPU/Apple Silicon/NVIDIA, serves both chat and embeddings, supports
**JSON-schema constrained output** (`format`) and turning Qwen3 "thinking" off, which the blueprint requires (§12.3).

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S03-1 | One `LLM.chat_json(role, system, user, schema, task, meta)` port; Ollama, OpenAI-compatible, fixture and scripted adapters |
| S03-2 | Temperature 0, thinking off, explicit context size (Ollama defaults to 4K: would silently truncate extraction prompts) |
| S03-3 | Resilience: timeout, retry with backoff on transient errors, circuit breaker, lenient JSON repair, **fallback main → fast model** (standby, §12.3) |
| S03-4 | Clear, actionable errors (`ollama pull <model>`; server unreachable) mapped to `ModelUnavailable` / `ModelOutputInvalid` |
| S03-5 | Embedder validates dimension (schema is `vector(1024)`) and L2-normalises; hashing embedder is deterministic |
| S03-6 | Negative tests: server down, 500s, 404 model missing, malformed/empty/fenced/`<think>` output, wrong embedding dimension, breaker open/half-open |

## 2. Plan

1. `adapters/jsonutil.py`: lenient JSON extraction/repair.
2. `adapters/llm.py`: port, `OllamaLLM`, `OpenAICompatLLM`, `FixtureLLM`, `ResilientLLM` (retry/breaker/fallback).
3. `adapters/embed.py`: port, `OllamaEmbedder`, `HashingEmbedder`.
4. `adapters/rerank.py`: port, `NoopReranker`, `CrossEncoderReranker`.
5. `adapters/factory.py`: build from settings; `adapters/testing.py`: `ScriptedLLM`.
6. Unit tests with `httpx.MockTransport` (no network).

## 3. Execution report

**Built:** `adapters/{jsonutil,llm,embed,rerank,factory,testing}.py`.

**Verified:** `tests/unit/test_adapters.py` → 49 passed (HTTP mocked with `httpx.MockTransport`: no network, no model).

| Criterion | Evidence |
| --------- | -------- |
| S03-1 port + adapters | Ollama, OpenAI-compatible, fixture, scripted all satisfy the same `LLM` protocol |
| S03-2 settings | request body asserted: `temperature 0`, `think false`, `options.num_ctx`, `format` = JSON schema |
| S03-3 resilience | 5xx → retry with backoff → success; N failures → breaker opens, call short-circuits; cooldown → half-open probe; main fails → fast model answers |
| S03-4 errors | 404 → message names `ollama pull <model>`; connection refused → `ModelUnavailable` |
| S03-5 embeddings | wrong dimension → error; vectors are unit length; hashing embedder deterministic and 1024-d |
| S03-6 negatives | empty output, ``` fenced JSON, `<think>` blocks, trailing commas, truncated JSON, non-object JSON |

**NOT verified here:** a real Ollama / vLLM server. The sandbox has no model weights and no GPU. The HTTP shape follows
Ollama's documented `/api/chat` and `/api/embed`; run `scripts/pull_models.sh` then `lw-eval` with `LLM_PROVIDER=ollama` to verify on your machine.
