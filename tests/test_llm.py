"""Test client Gemini API với API giả lập (không gọi mạng)."""

import pytest
import requests

from digest import llm, storage

KEY = "AIza-secret-key"


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self.payload, self.text = status, payload, text

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


def client(post=None, get=None, key=KEY):
    return llm.LLMClient(storage.load_settings()["llm"], key=key, post=post, get=get)


OK = {"candidates": [{"content": {"parts": [{"text": '{"items": '}, {"text": "[]}"}]}}],
      "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20}}


def test_chat_ok_builds_request_and_counts():
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return Resp(200, OK)

    c = client(post)
    res = c.chat("hi", system="sys", model="models/gemini-x", json_mode=True)
    assert res.text == '{"items": []}' and res.model == "gemini-x"
    url, headers, body = calls[0]
    assert url.endswith("/models/gemini-x:generateContent") and KEY not in url
    assert headers["x-goog-api-key"] == KEY
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert c.calls == 1 and c.tokens == {"prompt": 100, "completion": 20}


def test_quota_errors_and_key_never_leaks():
    with pytest.raises(llm.LLMQuotaError):
        client(lambda *a, **k: Resp(429, text="quota")).chat("x", model="m")
    with pytest.raises(llm.LLMError) as e:
        client(lambda *a, **k: Resp(400, text=f"API key not valid: {KEY}")).chat("x", model="m")
    assert KEY not in str(e.value) and "***" in str(e.value)
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}})).chat("x", model="m")

    def down(*a, **k):
        raise requests.ConnectionError(f"down {KEY}")

    with pytest.raises(llm.LLMError) as e:
        client(down).chat("x", model="m")
    assert KEY not in str(e.value)
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, OK), key="").chat("x", model="m")
    with pytest.raises(llm.LLMError):
        client(lambda *a, **k: Resp(200, OK)).chat("x")  # chưa chọn mô hình


MODELS = {"models": [
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
]}


def test_list_models_filters_generate_content():
    names = [m["name"] for m in client(get=lambda *a, **k: Resp(200, MODELS)).list_models()]
    assert "models/text-embedding-004" not in names and len(names) == 5


def test_list_models_follows_pages():
    pages = iter([Resp(200, {"models": MODELS["models"][:1], "nextPageToken": "p2"}),
                  Resp(200, {"models": MODELS["models"][1:2]})])
    assert len(client(get=lambda *a, **k: next(pages)).list_models()) == 2


def test_pick_models_prefers_stable_flash_lite():
    picked = llm.pick_models(client(get=lambda *a, **k: Resp(200, MODELS)).list_models(), ["flash-lite", "flash"], 3)
    assert picked == ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"]  # bản preview và ảnh bị đẩy/bỏ


def test_check_reports_each_model():
    def post(url, headers, json, timeout):
        return Resp(200, OK) if "flash-lite" in url else Resp(429, text="quota")

    report = llm.check(client(post, lambda *a, **k: Resp(200, MODELS)), log=lambda *a: None)
    assert report["models"]["gemini-2.5-flash-lite"]["ok"]
    assert not report["models"]["gemini-2.5-flash"]["ok"]


def test_check_without_key_and_with_bad_list():
    assert llm.check(client(key=""), log=lambda *a: None)["key"] is False
    report = llm.check(client(get=lambda *a, **k: Resp(403, text="forbidden")), log=lambda *a: None)
    assert report["models"] == {} and report["available"] == []
