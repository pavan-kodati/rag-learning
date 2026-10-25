"""S03: adapters with mocked HTTP (no network, no models)."""

from __future__ import annotations

import json

import httpx
import pytest

from legal_workspace.adapters.embed import HashingEmbedder, OllamaEmbedder, cosine
from legal_workspace.adapters.jsonutil import loads_lenient
from legal_workspace.adapters.llm import (
    CircuitBreaker,
    FixtureLLM,
    OllamaBackend,
    OpenAICompatBackend,
    ResilientLLM,
)
from legal_workspace.adapters.rerank import NoopReranker
from legal_workspace.errors import ModelOutputInvalid, ModelUnavailable

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)


def ollama(handler, **kw):
    return OllamaBackend("http://ollama", "qwen3:8b", "qwen3:4b", 16384, 8192, client=client(handler), **kw)


def ok(content):
    return httpx.Response(200, json={"message": {"content": content}})


# ------------------------------------------------------------------------------------ json utils
@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"x": 1}', {"x": 1}),
        ('```json\n{"x": 1}\n```', {"x": 1}),
        ('<think>hmm {"x": 99}</think>{"x": 1}', {"x": 1}),
        ('Sure! Here you go: {"x": 1} hope it helps', {"x": 1}),
        ('{"x": 1,}', {"x": 1}),
        ('{"s": "a } brace in string", "x": 2}', {"s": "a } brace in string", "x": 2}),
        ('[{"x": 1}]', [{"x": 1}]),
    ],
)
def test_loads_lenient(text, expected):
    assert loads_lenient(text) == expected


@pytest.mark.parametrize(
    "text", ["", "   ", "no json at all", "{unterminated", "<think>only thoughts</think>"]
)
def test_loads_lenient_rejects(text):
    with pytest.raises(ValueError):
        loads_lenient(text)


# ------------------------------------------------------------------------------------------ ollama
def test_ollama_request_shape_thinking_off_context_and_schema():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return ok('{"x": 1}')

    out = ResilientLLM(ollama(handler)).chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert out == {"x": 1}
    assert seen["model"] == "qwen3:8b" and seen["think"] is False and seen["format"] == SCHEMA
    assert (
        seen["options"]["temperature"] == 0 and seen["options"]["num_ctx"] == 16384
    )  # not Ollama's 4K default


def test_ollama_fast_role_uses_fast_model_and_context():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return ok('{"x": 1}')

    ResilientLLM(ollama(handler)).chat_json(role="fast", system="s", user="u", schema=SCHEMA)
    assert seen["model"] == "qwen3:4b" and seen["options"]["num_ctx"] == 8192


def test_ollama_think_unsupported_is_retried_without_the_flag():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append("think" in body)
        if "think" in body:
            return httpx.Response(400, text='{"error":"\\"llama3\\" does not support thinking"}')
        return ok('{"x": 3}')

    assert ResilientLLM(ollama(handler)).chat_json(role="main", system="s", user="u", schema=SCHEMA) == {
        "x": 3
    }
    assert calls == [True, False]


def test_ollama_down_maps_to_model_unavailable_with_hint():
    def handler(req):
        raise httpx.ConnectError("refused")

    llm = ResilientLLM(ollama(handler), retries=0, fallback_to_fast=False)
    with pytest.raises(ModelUnavailable) as ei:
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert "ollama serve" in ei.value.detail


def test_ollama_model_missing_is_not_retried_and_tells_the_user_what_to_pull():
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(404, json={"error": "model not found"})

    llm = ResilientLLM(ollama(handler), retries=3, fallback_to_fast=False, sleep=lambda s: None)
    with pytest.raises(ModelUnavailable) as ei:
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert "ollama pull qwen3:8b" in ei.value.detail and len(n) == 1


def test_main_model_missing_falls_back_to_fast_standby():
    def handler(req):
        body = json.loads(req.content)
        return httpx.Response(404, json={}) if body["model"] == "qwen3:8b" else ok('{"x": 7}')

    llm = ResilientLLM(ollama(handler), sleep=lambda s: None)
    assert llm.chat_json(role="main", system="s", user="u", schema=SCHEMA) == {"x": 7}
    assert llm.last_role_used == "fast"


def test_server_errors_retry_with_backoff_then_succeed():
    seq = iter([httpx.Response(503), httpx.Response(500), ok('{"x": 5}')])
    sleeps = []
    llm = ResilientLLM(ollama(lambda r: next(seq)), retries=2, sleep=sleeps.append)
    assert llm.chat_json(role="main", system="s", user="u", schema=SCHEMA) == {"x": 5}
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.5


def test_retries_exhausted_raises_last_error():
    llm = ResilientLLM(
        ollama(lambda r: httpx.Response(502)), retries=1, fallback_to_fast=False, sleep=lambda s: None
    )
    with pytest.raises(ModelUnavailable):
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)


def test_invalid_json_gets_a_nudge_then_succeeds():
    users = []
    outs = iter(["I think the answer is 4", '{"x": 4}'])

    def handler(req):
        users.append(json.loads(req.content)["messages"][1]["content"])
        return ok(next(outs))

    assert ResilientLLM(ollama(handler)).chat_json(role="main", system="s", user="u", schema=SCHEMA) == {
        "x": 4
    }
    assert "ONLY a valid JSON" in users[1] and "ONLY" not in users[0]


def test_persistently_invalid_json_raises_model_output_invalid():
    llm = ResilientLLM(ollama(lambda r: ok("nope")), retries=2)
    with pytest.raises(ModelOutputInvalid):
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)


def test_json_array_is_wrapped_and_scalar_rejected():
    assert ResilientLLM(ollama(lambda r: ok('[{"x":1}]'))).chat_json(
        role="main", system="s", user="u", schema=SCHEMA
    ) == {"items": [{"x": 1}]}
    with pytest.raises(ModelOutputInvalid):
        ResilientLLM(ollama(lambda r: ok("42")), retries=0).chat_json(
            role="main", system="s", user="u", schema=SCHEMA
        )


def test_response_without_message_is_invalid():
    llm = ResilientLLM(ollama(lambda r: httpx.Response(200, json={"oops": 1})), retries=0)
    with pytest.raises(ModelOutputInvalid):
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)


def test_client_error_400_is_not_retried():
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(400, text="bad schema")

    with pytest.raises(ModelOutputInvalid):
        ResilientLLM(ollama(handler), retries=3).chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert len(n) == 1


def test_timeout_is_reported_as_unavailable():
    def handler(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ModelUnavailable):
        ResilientLLM(ollama(handler), retries=0, fallback_to_fast=False).chat_json(
            role="main", system="s", user="u", schema=SCHEMA
        )


def test_ollama_health_lists_missing_models():
    def handler(req):
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    h = ollama(handler).health()
    assert h["ok"] is False and "qwen3:4b" in h["detail"]
    h2 = OllamaBackend(
        "http://o",
        "a",
        "a",
        1,
        1,
        client=client(lambda r: httpx.Response(200, json={"models": [{"name": "a:latest"}]})),
    ).health()
    assert h2["ok"] is True


def test_ollama_health_when_down():
    def handler(req):
        raise httpx.ConnectError("x")

    assert ollama(handler).health()["ok"] is False


# ------------------------------------------------------------------------------------ circuit breaker
def test_breaker_opens_then_half_opens_then_closes():
    now = [0.0]
    b = CircuitBreaker(threshold=2, cooldown_s=10, clock=lambda: now[0])
    assert b.allow() and b.state == "closed"
    b.failure()
    b.failure()
    assert not b.allow() and b.state == "open"
    now[0] = 11
    assert b.allow() and b.state == "half-open"
    b.success()
    assert b.state == "closed"


def test_open_breaker_fails_fast_without_calling_the_server():
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(503)

    br = CircuitBreaker(threshold=2, cooldown_s=60)
    llm = ResilientLLM(ollama(handler), retries=0, breaker=br, fallback_to_fast=False)
    for _ in range(2):
        with pytest.raises(ModelUnavailable):
            llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)
    calls_before = len(n)
    with pytest.raises(ModelUnavailable) as ei:
        llm.chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert "circuit" in ei.value.detail and len(n) == calls_before


# --------------------------------------------------------------------------------------- openai-compat
def test_openai_compat_request_and_response():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 2}'}}]})

    b = OpenAICompatBackend("http://vllm/v1", "k", "qwen3-8b", "qwen3-4b", client=client(handler))
    assert ResilientLLM(b).chat_json(role="main", system="s", user="u", schema=SCHEMA) == {"x": 2}
    assert seen["response_format"]["type"] == "json_schema" and seen["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert seen["temperature"] == 0 and seen["auth"] == "Bearer k"


@pytest.mark.parametrize(
    "status, exc",
    [(401, ModelUnavailable), (404, ModelUnavailable), (500, ModelUnavailable), (422, ModelOutputInvalid)],
)
def test_openai_compat_error_statuses(status, exc):
    b = OpenAICompatBackend(
        "http://v/v1", "k", "m", "m", client=client(lambda r: httpx.Response(status, text="e"))
    )
    with pytest.raises(exc):
        ResilientLLM(b, retries=0, fallback_to_fast=False).chat_json(
            role="main", system="s", user="u", schema=SCHEMA
        )


def test_openai_compat_auth_failure_does_not_fall_back():
    n = []

    def handler(req):
        n.append(json.loads(req.content)["model"])
        return httpx.Response(401)

    b = OpenAICompatBackend("http://v/v1", "bad", "big", "small", client=client(handler))
    with pytest.raises(ModelUnavailable):
        ResilientLLM(b).chat_json(role="main", system="s", user="u", schema=SCHEMA)
    assert n == ["big"]


def test_openai_compat_malformed_body():
    b = OpenAICompatBackend(
        "http://v/v1", "k", "m", "m", client=client(lambda r: httpx.Response(200, json={"nope": 1}))
    )
    with pytest.raises(ModelOutputInvalid):
        ResilientLLM(b, retries=0).chat_json(role="main", system="s", user="u", schema=SCHEMA)


# -------------------------------------------------------------------------------------------- fixture
def test_fixture_llm_replays_and_refuses_unknown_documents(tmp_path):
    (tmp_path / "f.json").write_text(
        json.dumps(
            {
                "classify": {"abc": {"document_type": "CONTRACT"}},
                "extract": {"abc": {"items": [{"slot": "a"}, {"slot": "b"}]}},
            }
        )
    )
    llm = FixtureLLM(tmp_path)
    assert llm.chat_json(
        role="fast", system="", user="", schema={}, task="classify", meta={"fixture_key": "abc"}
    ) == {"document_type": "CONTRACT"}
    assert llm.chat_json(
        role="main", system="", user="", schema={}, task="extract", meta={"fixture_key": "abc", "window": 1}
    ) == {"items": []}
    assert (
        len(
            llm.chat_json(
                role="main",
                system="",
                user="",
                schema={},
                task="extract",
                meta={"fixture_key": "abc", "window": 0},
            )["items"]
        )
        == 2
    )
    with pytest.raises(ModelUnavailable) as ei:
        llm.chat_json(role="main", system="", user="", schema={}, task="extract", meta={"fixture_key": "zzz"})
    assert "LLM_PROVIDER=ollama" in ei.value.detail
    assert llm.chat_json(role="fast", system="", user="", schema={}, task="route")["intents"] == [
        "FACTUAL_QA"
    ]
    with pytest.raises(ModelUnavailable):
        llm.chat_json(role="main", system="", user="", schema={}, task="answer")
    assert llm.supports_generation is False


def test_fixture_llm_with_missing_or_corrupt_dir(tmp_path):
    (tmp_path / "bad.json").write_text("{not json")
    assert FixtureLLM(tmp_path).health()["ok"] is False
    assert FixtureLLM(tmp_path / "missing").health()["ok"] is False


# ------------------------------------------------------------------------------------------- embedder
def test_hashing_embedder_is_deterministic_normalised_and_meaningful():
    e = HashingEmbedder()
    a, b, c = e.embed(
        ["delivery date of the goods", "delivery date of the goods", "bank statement of payments"]
    )
    assert a == b and len(a) == 1024
    assert abs(sum(x * x for x in a) - 1.0) < 1e-5
    related = e.embed(["when is delivery due for the goods"])[0]
    assert cosine(a, related) > cosine(a, c)
    assert e.embed([""])[0] == [0.0] * 1024  # empty text -> zero vector, no crash


def test_ollama_embedder_batches_normalises_and_validates_dimension():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(len(body["input"]))
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] + [0.0] * 1022 for _ in body["input"]]})

    e = OllamaEmbedder("http://o", "bge-m3", batch=2, client=client(handler))
    vecs = e.embed(["a", "b", "c", "d", "e"])
    assert calls == [2, 2, 1] and len(vecs) == 5
    assert vecs[0][:2] == pytest.approx([0.6, 0.8])


def test_ollama_embedder_rejects_wrong_dimension_with_actionable_message():
    e = OllamaEmbedder(
        "http://o",
        "nomic-embed-text",
        client=client(lambda r: httpx.Response(200, json={"embeddings": [[0.1] * 768]})),
    )
    with pytest.raises(ModelOutputInvalid) as ei:
        e.embed(["x"])
    assert "768" in ei.value.detail and "1024" in ei.value.detail


@pytest.mark.parametrize(
    "resp, exc",
    [
        (httpx.Response(404, json={}), ModelUnavailable),
        (httpx.Response(500), ModelUnavailable),
        (httpx.Response(400, text="bad"), ModelOutputInvalid),
        (httpx.Response(200, json={"x": 1}), ModelOutputInvalid),
        (httpx.Response(200, json={"embeddings": []}), ModelOutputInvalid),
    ],
)
def test_ollama_embedder_errors(resp, exc):
    with pytest.raises(exc):
        OllamaEmbedder("http://o", "bge-m3", client=client(lambda r: resp)).embed(["x"])


def test_ollama_embedder_down():
    def handler(req):
        raise httpx.ConnectError("x")

    e = OllamaEmbedder("http://o", "bge-m3", client=client(handler))
    with pytest.raises(ModelUnavailable):
        e.embed(["x"])
    assert e.health()["ok"] is False


def test_noop_reranker_preserves_order():
    s = NoopReranker().rerank("q", ["a", "b", "c"])
    assert s == sorted(s, reverse=True) and NoopReranker().rerank("q", []) == []
