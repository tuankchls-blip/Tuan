"""Máy dịch giả cho dichviet: thay claude-cli, google, mymemory trong test, không gọi mạng."""

from __future__ import annotations

from pathlib import Path

from dichviet import Translator, engines
from dichviet.config import Config
from dichviet.models import EngineError, EngineResult

ROOT = Path(__file__).resolve().parents[1]


class FakeEngine:
    """fn(text) → bản dịch; fn ném EngineError thì cả lô lỗi; trả "" thì đoạn đó không qua kiểm tra."""

    def __init__(self, name, fn=None, follows_style=None):
        self.name = name
        self.max_chars = 12000
        self.follows_style = (name == "claude-cli") if follows_style is None else follows_style
        self.fn = fn or (lambda t: "[vi] " + t)
        self.calls: list[list[str]] = []  # văn bản đã gửi, mỗi lần gọi một danh sách

    def available(self):
        return True

    def translate(self, batch, profile, glossary):
        self.calls.append([s.text for s in batch.segments])
        out = {s.id: (self.fn(s.text) if s.text.strip() else "") for s in batch.segments}
        return EngineResult(translations=out, usage={"model": "fake", "tokens_in": 1, "tokens_out": 1,
                                                     "cost_usd": 0.0})


def quota(_text):
    raise EngineError("Google chặn do gửi quá nhiều (429)", kind="quota")


def install(monkeypatch, **fns) -> dict[str, FakeEngine]:
    """Thay các máy trong REGISTRY của dichviet bằng máy giả; trả về {tên: máy giả}."""
    made = {name: FakeEngine(name, fns.get(name.replace("-", "_"))) for name in ("claude-cli", "google", "mymemory")}
    for name, eng in made.items():
        monkeypatch.setitem(engines.REGISTRY, name, lambda cfg, e=eng: e)
    return made


def make_translator() -> Translator:
    """Translator dùng đúng config/dichviet.yaml (và config/glossary.yaml) của bản tin, nhưng
    không ghi nhật ký và tắt kiểm tra sót tiếng Anh (máy giả trả "[vi] " + tiếng Anh)."""
    cfg = Config.load(ROOT / "config/dichviet.yaml")
    cfg.usage_dir = None
    cfg.disabled_checks = ["english"]
    return Translator(config=cfg)
