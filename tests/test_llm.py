"""Test client GitHub Models với API giả lập (không gọi mạng)."""

import pytest
import requests

from digest import llm, storage


class Resp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code, self.payload, self.headers, self.text = status, payload, headers or {}, text

    def json(self):
        return self.payload


def client(post=None, get=None, token="t"):
    return llm.LLMClient(storage.load_settings()["llm"], token=token, post=post, get=get)


OK = {"model": "openai/gpt-4.1-mini", "choices": [{"message": {"content": '{"items": []}'}}],
      "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def test_chat_ok_and_counts():
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return Resp(200, OK, {"X-RateLimit-Remaining-Requests": "149", "Server": "x"})

    c = client(post)
    res = c.chat([{"role": "user", "content": "hi"}], model="openai/gpt-4.1-mini", json_mode=True)
    assert res.text == '{"items": []}' and res.rate_limits == {"x-ratelimit-remaining-requests": "149"}
    url, headers, body = calls[0]
    assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer t"
    assert body["response_format"] == {"type": "json_object"}
    assert c.calls == 1 and c.tokens == {"prompt": 100, "completion": 20}


def test_quota_and_errors():
    with pytest.raises(llm.LLMQuotaError):
        client(lambda *a, **k: Resp(429, text="rate limit")).chat([], model="m")
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(500, text="boom")).chat([], model="m")
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, {"choices": []})).chat([], model="m")

    def down(*a, **k):
        raise requests.ConnectionError("down")

    with pytest.raises(llm.LLMError):
        client(down).chat([], model="m")
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, OK), token="").chat([], model="m")
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, OK)).chat([])  # chưa chọn mô hình


def test_check_reports_each_model():
    def post(url, headers, json, timeout):
        return Resp(200, OK) if json["model"] == "good" else Resp(404, text="unknown model")

    get = lambda *a, **k: Resp(200, [{"id": "good", "rate_limit_tier": "low"}])  # noqa: E731
    report = llm.check(client(post, get), ["good", "bad"], log=lambda *a: None)
    assert report["catalog"] == 1
    assert report["models"]["good"]["ok"] and not report["models"]["bad"]["ok"]


def test_check_without_token():
    report = llm.check(client(token=""), ["x"], log=lambda *a: None)
    assert report == {"token": False, "catalog": None, "models": {}}


def test_check_continues_when_catalog_is_not_json():
    class Bad(Resp):
        def json(self):
            raise ValueError("not json")

    report = llm.check(client(lambda *a, **k: Resp(200, OK), lambda *a, **k: Bad(200, text="")), ["m"],
                       log=lambda *a: None)
    assert report["catalog"] is None and report["models"]["m"]["ok"]
