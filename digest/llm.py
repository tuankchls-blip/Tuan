"""Gọi mô hình AI qua GitHub Models (API chat kiểu OpenAI), xác thực bằng GITHUB_TOKEN.

Mọi lỗi được đổi thành LLMError (hết hạn mức: LLMQuotaError) để nơi gọi chuyển sang đường lùi,
không làm hỏng lần chạy bản tin.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests


class LLMError(RuntimeError):
    """Lỗi khi gọi mô hình (mạng, máy chủ, đầu ra lạ)."""


class LLMQuotaError(LLMError):
    """Hết hạn mức (HTTP 429): không gọi tiếp trong lần chạy này."""


@dataclass
class LLMResult:
    text: str
    model: str
    seconds: float
    usage: dict[str, Any] = field(default_factory=dict)
    rate_limits: dict[str, str] = field(default_factory=dict)  # header x-ratelimit-*


# post(url, headers, json, timeout) -> requests.Response; test thay bằng hàm giả
Poster = Callable[..., Any]


class LLMClient:
    def __init__(self, cfg: dict[str, Any], token: str | None = None, post: Poster | None = None,
                 get: Poster | None = None) -> None:
        self.cfg = cfg
        self.token = token if token is not None else os.environ.get(cfg.get("token_env", "GITHUB_TOKEN"), "")
        self._post = post or requests.post
        self._get = get or requests.get
        self.calls = 0
        self.tokens = {"prompt": 0, "completion": 0}

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "Content-Type": "application/json"}
        if self.cfg.get("api_version"):
            headers["X-GitHub-Api-Version"] = self.cfg["api_version"]
        return headers

    def probe(self, model: str, log: Callable[[str], None]) -> None:
        """Chẩn đoán: thử vài biến thể header, in mã HTTP, kiểu nội dung, nội dung trả về."""
        body = {"model": model, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 5}
        variants = {
            "2022-11-28": {"X-GitHub-Api-Version": "2022-11-28", "Accept": "application/vnd.github+json"},
            "2026-03-10": {"X-GitHub-Api-Version": "2026-03-10", "Accept": "application/vnd.github+json"},
            "không header phiên bản, Accept json": {"Accept": "application/json"},
        }
        for name, extra in variants.items():
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", **extra}
            try:
                r = self._post(self.cfg["endpoint"], headers=headers, json=body, timeout=30)
                log(f"  [{name}] HTTP {r.status_code} · {r.headers.get('content-type', '')} · {r.text[:160]!r}")
            except requests.RequestException as exc:
                log(f"  [{name}] lỗi mạng: {exc}")

    def catalog(self) -> list[dict[str, Any]]:
        """Danh mục mô hình GitHub Models (id, tên, hạn mức)."""
        r = self._get(self.cfg["catalog_url"], headers=self._headers(), timeout=self.cfg.get("timeout_seconds", 60))
        if r.status_code != 200:
            raise LLMError(f"catalog HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            ctype = r.headers.get("content-type", "")
            raise LLMError(f"catalog không phải JSON ({ctype}): {r.text[:200]!r}") from exc

    def chat(self, messages: list[dict[str, str]], model: str | None = None, max_tokens: int = 1500,
             json_mode: bool = False) -> LLMResult:
        model = model or self.cfg.get("model")
        if not model:
            raise LLMError("chưa chọn mô hình (llm.model trong settings.yaml)")
        if not self.token:
            raise LLMError(f"thiếu token ({self.cfg.get('token_env', 'GITHUB_TOKEN')})")
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": self.cfg.get("temperature", 0.2)}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        start = time.monotonic()
        try:
            r = self._post(self.cfg["endpoint"], headers=self._headers(), json=body,
                           timeout=self.cfg.get("timeout_seconds", 60))
        except requests.RequestException as exc:
            raise LLMError(f"lỗi mạng: {type(exc).__name__}: {str(exc)[:150]}") from exc
        self.calls += 1
        limits = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
        if r.status_code == 429:
            raise LLMQuotaError(f"hết hạn mức: {r.text[:200]}")
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            ctype = r.headers.get("content-type", "")
            raise LLMError(f"đầu ra lạ ({ctype}): {r.text[:120]!r}") from exc
        usage = data.get("usage") or {}
        self.tokens["prompt"] += usage.get("prompt_tokens", 0) or 0
        self.tokens["completion"] += usage.get("completion_tokens", 0) or 0
        return LLMResult(text=text, model=data.get("model", model), seconds=round(time.monotonic() - start, 1),
                         usage=usage, rate_limits=limits)


# Câu thử cho llm-check: tiêu đề thật mà MyMemory từng dịch sai tên riêng
CHECK_ITEMS = [
    {"id": "t1", "title": "Welcome Le Chonk: Mistral Large 4 on Hugging Face",
     "summary": "The French AI lab claims its latest open-weight LLM matches the best models on coding benchmarks."},
    {"id": "t2", "title": "Alpine Linux rebuilds GitLab after attempted RCE attack",
     "summary": "Hackers tried to exploit a critical GitLab flaw in Alpine Linux's development infrastructure."},
]


def check(client: LLMClient, candidates: list[str], log: Callable[[str], None] = print) -> dict[str, Any]:
    """Kiểm tra GitHub Models: mô hình nào dùng được, chất lượng dịch thử, hạn mức. Không ném lỗi."""
    report: dict[str, Any] = {"token": client.available, "catalog": None, "models": {}}
    if not client.available:
        log("Không có GITHUB_TOKEN: chỉ chạy được trong GitHub Actions (cần quyền models: read)")
        return report
    try:
        cat = client.catalog()
        ids = {m.get("id"): m for m in cat}
        report["catalog"] = len(cat)
        log(f"Danh mục: {len(cat)} mô hình")
        for c in candidates:
            m = ids.get(c)
            log(f"  {c}: {'có' if m else 'KHÔNG có'}" + (f" · tier {m.get('rate_limit_tier')}" if m else ""))
    except LLMError as exc:
        log(f"Không đọc được danh mục: {exc}")
    if candidates:
        log(f"Chẩn đoán với {candidates[0]}:")
        client.probe(candidates[0], log)
    prompt = ("Dịch tiêu đề và tóm tắt sau sang tiếng Việt, tự nhiên như báo công nghệ. Giữ nguyên tên riêng, "
              "tên mô hình, tên công ty và thuật ngữ như LLM, open-weight, benchmark, RCE. Trả về JSON "
              '{"items": [{"id", "title_vi", "summary_vi"}]}, không thêm chữ nào khác.\n\n'
              + json.dumps(CHECK_ITEMS, ensure_ascii=False))
    for c in candidates:
        try:
            res = client.chat([{"role": "user", "content": prompt}], model=c, max_tokens=600, json_mode=True)
            report["models"][c] = {"ok": True, "seconds": res.seconds, "usage": res.usage,
                                   "rate_limits": res.rate_limits, "text": res.text[:600]}
            log(f"\n== {c}: OK {res.seconds}s · token {res.usage}")
            log(f"   hạn mức: {res.rate_limits}")
            log("   " + res.text[:600].replace("\n", "\n   "))
        except LLMError as exc:
            report["models"][c] = {"ok": False, "error": str(exc)}
            log(f"\n== {c}: LỖI {exc}")
    return report
