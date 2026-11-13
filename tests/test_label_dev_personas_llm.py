"""Offline tests for strict parsing in the development labeling script."""

import json
from io import BytesIO

import pytest

from scripts import label_dev_personas_llm as labeling
from scripts.label_dev_personas_llm import _request, parse_structured, probe_response


@pytest.mark.parametrize(
    "content",
    [
        '{"label":"eligible","reason":"The facts match."}',
        '```json\n{"label":"not_eligible","reason":"An age rule excludes the case."}\n```',
        'Reasoning omitted. {"label":"need_more_information","reason":"Age is missing."}',
    ],
)
def test_parse_structured_accepts_json_with_common_wrappers(content: str) -> None:
    parsed = parse_structured(content)

    assert parsed["label"] in {
        "eligible", "not_eligible", "need_more_information",
    }
    assert parsed["reason"]


@pytest.mark.parametrize(
    "content",
    [
        "No structured answer was returned.",
        '{"label":"unknown","reason":"Invalid label."}',
        '{"label":"eligible","reason":" "}',
    ],
)
def test_parse_structured_rejects_missing_or_invalid_labels(content: str) -> None:
    with pytest.raises(ValueError, match="no valid label JSON object"):
        parse_structured(content)


@pytest.mark.parametrize(
    ("raw", "stage"),
    [
        (b"not json", "response_json"),
        (b'{"usage":{"cost":"not numeric"}}', "cost_parse"),
        (b'{"usage":{"cost":0.51}}', "cost_above_limit"),
        (b'{"choices":[]}', "response_schema"),
        (b'{"choices":[{"message":{"content":null}}]}', "structured_output"),
        (b'{"choices":[{"finish_reason":"length","message":{"content":"{\\"label\\""}}]}', "structured_output"),
    ],
)
def test_probe_distinguishes_failure_stages(raw: bytes, stage: str) -> None:
    assert probe_response(raw)["stage"] == stage


def test_probe_reports_safe_metadata_without_response_content() -> None:
    raw = json.dumps({
        "usage": {"cost": 0.0, "completion_tokens": 200},
        "choices": [{
            "finish_reason": "length",
            "message": {"content": "private output", "reasoning": "private reasoning"},
        }],
    }).encode()
    result = probe_response(raw)
    assert result == {
        "stage": "structured_output",
        "cost_usd_reported": 0.0,
        "finish_reason": "length",
        "content_type": "str",
        "content_length": 14,
        "reasoning_present": True,
        "completion_tokens": 200,
    }
    assert "private" not in json.dumps(result)


def test_probe_accepts_valid_response() -> None:
    raw = json.dumps({
        "choices": [{"message": {
            "content": '{"label":"eligible","reason":"Criteria met."}',
        }}],
    }).encode()
    assert probe_response(raw)["stage"] == "success"


def test_probe_request_limits_tokens_and_requests_no_reasoning() -> None:
    request = _request("synthetic-key", "synthetic prompt", max_tokens=1024, disable_reasoning=True)
    payload = json.loads(request.data)
    assert payload["max_tokens"] == 1024
    assert payload["reasoning"] == {"effort": "none"}


def test_run_probe_sends_adjusted_request_once(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []
    monkeypatch.setenv(labeling.KEY_NAME, "synthetic-key")
    monkeypatch.setattr(labeling, "load_cases", lambda: [{"scheme_id": "DEMO", "facts": {}}])
    monkeypatch.setattr(labeling, "load_passages", lambda: {"DEMO": "Synthetic criteria."})

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return BytesIO(json.dumps({
            "choices": [{"message": {
                "content": '{"label":"eligible","reason":"Criteria met."}',
            }}],
        }).encode())

    monkeypatch.setattr(labeling.urllib.request, "urlopen", respond)
    assert labeling.run_probe() == 0
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 1024
    assert requests[0]["reasoning"] == {"effort": "none"}


def test_call_model_preserves_cost_on_bad_output(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return BytesIO(json.dumps({
            "usage": {"cost": 0.1},
            "choices": [{"message": {"content": None}}],
        }).encode())

    monkeypatch.setattr(labeling.urllib.request, "urlopen", respond)
    with pytest.raises(labeling.ModelResponseError) as error:
        labeling.call_model("synthetic-key", "synthetic prompt")
    assert error.value.cost == 0.1
    assert requests[0]["max_tokens"] == 1024
    assert requests[0]["reasoning"] == {"effort": "none"}


def test_call_model_stops_on_high_reported_cost_even_if_output_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labeling.urllib.request, "urlopen", lambda *args, **kwargs: BytesIO(
        b'{"usage":{"cost":0.51},"choices":[{"message":{"content":null}}]}'
    ))
    with pytest.raises(labeling.StopRun) as error:
        labeling.call_model("synthetic-key", "synthetic prompt")
    assert error.value.reason == "cost_above_limit"
    assert error.value.cost == 0.51
