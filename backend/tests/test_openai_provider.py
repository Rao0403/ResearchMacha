from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from app import ai


def fake_client(handler):
    return OpenAI(
        api_key="test-not-real", base_url="https://openai.invalid/v1", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def completed_response(text: str, *, status="completed", output=None, reason=None):
    return {
        "id": "resp_test", "object": "response", "created_at": 0, "model": "gpt-6-luna",
        "status": status, "incomplete_details": {"reason": reason} if reason else None,
        "output": output if output is not None else [{
            "type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                  "input_tokens_details": {"cached_tokens": 5}, "output_tokens_details": {"reasoning_tokens": 0}},
    }


def invoke(client, output_model=ai.ResearchPlan, **kwargs):
    return ai.invoke_structured_json(
        client, output_model, "Use supplied evidence", "Question: {question}",
        {"question": "Q", **kwargs},
    )


def test_actual_sdk_request_uses_responses_strict_evidence_none_reasoning_and_usage(caplog):
    bodies = []

    def handler(request):
        assert request.url.path == "/v1/responses"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, headers={"x-request-id": "req_test"},
                              json=completed_response('{"answer":"Grounded","chunk_ids":["e1"]}'))

    caplog.set_level("INFO", logger="uvicorn.error")
    with fake_client(handler) as client:
        result = invoke(client, ai.ChatDraft, evidence_ids=["e1", "e2"])

    body = bodies[0]
    assert result.chunk_ids == ["e1"]
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "none"}
    assert body["store"] is False and body["stream"] is False
    assert body["max_output_tokens"] == ai.settings.ai_chat_max_output_tokens
    schema = body["text"]["format"]["schema"]
    assert body["text"]["format"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["answer", "chunk_ids"]
    assert schema["properties"]["chunk_ids"]["items"]["enum"] == ["e1", "e2"]
    example = body["input"][0]["content"].split("Example valid JSON:\n", 1)[1]
    assert json.loads(example)["chunk_ids"] == ["e1"]
    assert '"input_tokens": 20' in caplog.text
    assert '"cached_input_tokens": 5' in caplog.text
    assert '"request_id": "req_test"' in caplog.text
    assert "test-not-real" not in caplog.text


@pytest.mark.parametrize(("status", "code", "error_type", "calls_expected"), [
    (401, "invalid_api_key", ai.AIAuthenticationError, 1),
    (403, "access_denied", ai.AIAuthenticationError, 1),
    (400, "invalid_json_schema", ai.AIConfigurationError, 1),
    (404, "model_not_found", ai.AIConfigurationError, 1),
    (429, "insufficient_quota", ai.AIQuotaError, 1),
    (429, "rate_limit_exceeded", ai.AIRateLimitError, 2),
    (500, "server_error", ai.AITransportError, 1),
])
def test_provider_errors_are_typed_and_never_cause_unbounded_retries(monkeypatch, status, code, error_type, calls_expected):
    requests = []
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: None)

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "Private server detail", "type": code, "code": code}})

    with fake_client(handler) as client, pytest.raises(error_type) as raised:
        invoke(client)

    assert len(requests) == calls_expected
    assert "Private server detail" not in str(raised.value)


def test_transport_timeout_does_not_retry():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("No response", request=request)

    with fake_client(handler) as client, pytest.raises(ai.AIProviderError, match="repair attempt skipped"):
        invoke(client)
    assert len(requests) == 1


@pytest.mark.parametrize("kind", ["refusal", "incomplete"])
def test_refusal_and_truncated_output_do_not_trigger_another_paid_attempt(kind):
    requests = []

    def handler(request):
        requests.append(request)
        if kind == "refusal":
            response = completed_response("", output=[{
                "id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "refusal", "refusal": "Unable to answer"}],
            }])
        else:
            response = completed_response("{", status="incomplete", reason="max_output_tokens")
        return httpx.Response(200, json=response)

    error_type = ai.AIRefusalError if kind == "refusal" else ai.AIIncompleteError
    with fake_client(handler) as client, pytest.raises(error_type):
        invoke(client)
    assert len(requests) == 1


def test_embedding_sdk_batches_orders_and_records_usage(caplog):
    batches = []

    def handler(request):
        body = json.loads(request.content)
        batches.append(body)
        assert body["model"] == "text-embedding-3-small"
        return httpx.Response(200, json={
            "object": "list", "model": body["model"],
            "data": [{"object": "embedding", "index": index, "embedding": [float(index), 1.0]}
                     for index in reversed(range(len(body["input"])))],
            "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])},
        })

    caplog.set_level("INFO", logger="uvicorn.error")
    model = object.__new__(ai.OpenAIEmbeddingModel)
    with fake_client(handler) as client:
        model.client = client
        result = model.embed_documents(["evidence"] * 65)

    assert [len(body["input"]) for body in batches] == [64, 1]
    assert len(result) == 65
    assert result[0] == [0.0, 1.0] and result[63] == [63.0, 1.0]
    assert '"operation": "embeddings"' in caplog.text


def test_missing_key_is_detected_without_network(monkeypatch):
    monkeypatch.setattr(ai.settings, "ai_provider", "openai")
    monkeypatch.setattr(ai.settings, "openai_api_key", "")
    with pytest.raises(ai.AIConfigurationError, match="OPENAI_API_KEY"):
        ai.get_ai_provider()


@pytest.mark.parametrize("output_model", [
    ai.ResearchPlan, ai.CandidateSelection, ai.PaperSummaryDraft,
    ai.ResearchBriefDraft, ai.BatchSummary, ai.BatchComparisonDraft, ai.ChatDraft,
])
def test_all_generation_operations_send_strict_schemas_and_their_own_budgets(output_model):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json=completed_response(json.dumps(ai.STRUCTURED_OUTPUT_EXAMPLES[output_model.__name__])))

    with fake_client(handler) as client:
        result = invoke(client, output_model)

    assert isinstance(result, output_model)
    assert bodies[0]["max_output_tokens"] == ai.output_budget(output_model.__name__)

    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node.get("properties", {}))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(bodies[0]["text"]["format"]["schema"])


def test_clients_disable_hidden_retries_and_use_separate_timeouts(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "OpenAI", lambda **kwargs: calls.append(kwargs) or SimpleNamespace())
    ai.build_chat_model()
    ai.build_embedding_model()
    assert [call["timeout"] for call in calls] == [180, 60]
    assert all(call["max_retries"] == 0 for call in calls)
