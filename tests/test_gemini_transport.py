import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from ai import gemini_client
from app_logging import clear_events, get_events


@pytest.mark.parametrize("wrapped", [False, True])
def test_read_timeout_retries_with_longer_timeout_and_same_payload(wrapped):
    clear_events()
    error = TimeoutError("The read operation timed out")
    if wrapped:
        error = URLError(error)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.side_effect = [
        error,
        b'{"candidates":[{"content":{"parts":[{"text":"recovered"}]}}]}',
    ]
    image = Mock(width=640, height=480)
    with patch.object(gemini_client, "urlopen", return_value=response) as send, patch.object(
            gemini_client, "redact_screen", return_value=(image, "safe prompt", None)) as redact, patch.object(
            gemini_client.time, "sleep") as sleep:
        result = gemini_client.request_gemini(
            "screen prompt", {"api_key": "test-credential", "model": "test-model"},
            image=image, response_schema={"type": "object"},
            log_context={"trace_id": "timeout-test", "source": "activity"})

    assert result == "recovered"
    assert send.call_count == 2
    assert all(call.kwargs["timeout"] == 120 for call in send.call_args_list)
    assert send.call_args_list[0].args[0] is send.call_args_list[1].args[0]
    redact.assert_called_once()
    sleep.assert_called_once_with(1)
    payload = json.loads(send.call_args.args[0].data)
    assert payload["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    events = get_events()
    request = next(event for event in events if event.event == "gemini.request")
    assert request.data["timeout_seconds"] == 120
    timeouts = [event for event in events if event.event == "gemini.timeout"]
    assert len(timeouts) == 1
    assert timeouts[0].trace_id == "timeout-test"
    assert timeouts[0].data["attempt"] == 1


@pytest.mark.parametrize("wrapped", [False, True])
def test_connection_timeouts_stop_after_three_attempts(wrapped):
    clear_events()
    error = TimeoutError("timed out")
    if wrapped:
        error = URLError(error)
    with patch.object(gemini_client, "urlopen", side_effect=error) as send, patch.object(
            gemini_client.time, "sleep") as sleep:
        result = gemini_client.request_gemini("hello", {"api_key": "test-credential"})

    assert result.startswith("[gemini error]")
    assert send.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]
    timeouts = [event for event in get_events() if event.event == "gemini.timeout"]
    assert len(timeouts) == 3
    assert timeouts[-1].level == "ERROR"


@pytest.mark.parametrize("error", [
    URLError("connection refused"),
    HTTPError("https://example.invalid", 403, "Forbidden", {}, None),
    ValueError("invalid response"),
])
def test_permanent_errors_are_not_retried(error):
    with patch.object(gemini_client, "urlopen", side_effect=error) as send, patch.object(
            gemini_client.time, "sleep") as sleep:
        result = gemini_client.request_gemini("hello", {"api_key": "test-credential"})

    assert result.startswith("[gemini error]")
    send.assert_called_once()
    sleep.assert_not_called()
