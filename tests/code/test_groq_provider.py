import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from docguard.ai.files import ProposalError
from docguard.ai.provider import generate, request_payload

DECISION = {
    "action": "unchanged",
    "summary": "Correct",
    "content": None,
    "warnings": [],
}


def test_experimental_prompt_schema_are_explicit_and_share_transport():
    schema = {"type": "object", "properties": {"supported": {"type": "boolean"}}}
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            envelope('{"supported": true}')
        ).encode()
        result = generate(
            "test",
            {"document_text": "doc"},
            provider="groq",
            api_key="test",
            instructions="Check support",
            schema=schema,
        )
        payload = json.loads(builder.return_value.open.call_args.args[0].data)
        assert payload["messages"][0]["content"] == "Check support"
        assert payload["response_format"]["json_schema"]["schema"] == schema
        assert result == {"supported": True}
        assert (
            payload["max_completion_tokens"]
            == request_payload("test", {"document_text": "doc"}, "groq")[
                "max_completion_tokens"
            ]
        )
    with pytest.raises(ProposalError, match="together"):
        generate(
            "test", {}, provider="groq", api_key="test", instructions="Check support"
        )


def envelope(content=None, finish="stop"):
    return {
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": json.dumps(DECISION) if content is None else content
                },
            }
        ]
    }


def test_groq_success_uses_only_groq_key_and_endpoint():
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            envelope()
        ).encode()
        assert (
            generate(
                "openai/gpt-oss-120b",
                {"document_text": "text"},
                provider="groq",
                api_key="groq-test-key",
            )
            == DECISION
        )
        req = builder.return_value.open.call_args.args[0]
        assert req.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert req.get_header("Authorization") == "Bearer groq-test-key"
        payload = json.loads(req.data)
        assert payload == request_payload(
            "openai/gpt-oss-120b", {"document_text": "text"}, "groq"
        )
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert "groq-test-key" not in req.data.decode()
        assert "tools" not in payload
        assert builder.return_value.open.call_args.kwargs["timeout"] == 60


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"choices": []},
        {"choices": [{}, {}]},
        envelope(finish="length"),
        envelope(finish="tool_calls"),
        envelope("{"),
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "{}", "refusal": "no"}}
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    ],
)
def test_invalid_groq_responses_rejected(response):
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            response
        ).encode()
        with pytest.raises(ProposalError):
            generate("test", {}, provider="groq", api_key="test")


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://api.groq.com", 401, "private", {}, None),
        HTTPError("https://api.groq.com", 400, "private", {}, None),
        HTTPError("https://api.groq.com", 429, "private", {}, None),
        URLError("private"),
        TimeoutError(),
    ],
)
def test_groq_errors_sanitized_and_no_retry(error):
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.side_effect = error
        with pytest.raises(ProposalError) as raised:
            generate("test", {}, provider="groq", api_key="private-key")
        assert "Groq" in str(raised.value)
        assert "private" not in str(raised.value)
        assert builder.return_value.open.call_count == 1


def test_missing_key_does_not_fall_back_to_openai():
    with patch("docguard.ai.provider.build_opener") as builder:
        with pytest.raises(ProposalError, match="GROQ_API_KEY"):
            generate("test", {}, provider="groq", api_key="")
        builder.assert_not_called()


def test_usage_reports_only_nonnegative_integer_token_counts():
    response = envelope()
    response["usage"] = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "other": "private",
    }
    captured = []
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            response
        ).encode()
        generate("test", {}, provider="groq", api_key="key", usage_sink=captured.append)
        assert captured == [
            {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        ]
        response["usage"] = {
            "prompt_tokens": True,
            "completion_tokens": -1,
            "total_tokens": "120",
        }
        builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            response
        ).encode()
        generate("test", {}, provider="groq", api_key="key", usage_sink=captured.append)
        assert captured[-1] == {}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("7", 7),
        ("0", 0),
        ("invalid", None),
        ("-1", None),
        ("NaN", None),
        ("inf", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0),
    ],
)
def test_retry_after_parsing(value, expected):
    from docguard.ai.provider import retry_after_seconds

    assert retry_after_seconds(value) == expected


def test_retry_after_future_http_date():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from docguard.ai.provider import retry_after_seconds

    value = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True
    )
    assert 28 <= retry_after_seconds(value) <= 30


def test_http_error_retains_only_safe_retry_metadata():
    from docguard.ai.provider import ProviderError

    error = HTTPError(
        "https://api.groq.com", 429, "private", {"Retry-After": "12"}, None
    )
    with patch("docguard.ai.provider.build_opener") as builder:
        builder.return_value.open.side_effect = error
        with pytest.raises(ProviderError) as raised:
            generate("test", {}, provider="groq", api_key="private-key")
    assert raised.value.retry_after == 12
    assert "private" not in str(raised.value)
