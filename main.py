"""Điểm khởi động của ai-daily-digest.

    python main.py daily [--date YYYY-MM-DD] [--no-claude] [--no-google] [--no-mymemory]
    python main.py weekly | monthly | quarterly | yearly [--date YYYY-MM-DD]
    python main.py due [--date YYYY-MM-DD]          # các bản tổng hợp đến hạn (workflow gọi sau bản ngày)
    python main.py retranslate --date YYYY-MM-DD    # dịch bù tin "chưa dịch" của một bản ngày đã lưu
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from digest import aggregator, classifier, fetcher, filters, scorer, storage, translator
from digest.renderer import Renderer
from digest.storage import Storage

ROOT = Path(__file__).resolve().parent


@dataclass
class DailyResult:
    day: date
    json_path: Path
    html_path: Path
    usage_path: Path
    summary: dict[str, Any]


def run_daily(
    day: date | None = None,
    root: Path = ROOT,
    use_claude: bool = True,
    use_google: bool = True,
    getter: fetcher.Getter | None = None,
    runner: translator.Runner = subprocess.run,
    google: translator.MachineBackend | None = None,
    use_mymemory: bool = True,
    mymemory: translator.MachineBackend | None = None,
    now: datetime | None = None,
    log=print,
) -> DailyResult:
    """Tạo bản tin của một ngày: thu thập → lọc → gom → chấm điểm → phân mục → dịch → lưu → xuất HTML."""
    started = time.monotonic()
    settings = storage.load_settings()
    all_sources = storage.load_sources(include_disabled=True)
    sources_list = [s for s in all_sources if s.enabled]
    sources = {s.id: s for s in all_sources}
    paths = settings["paths"]
    store = Storage(root / paths["data_dir"])
    tz = ZoneInfo(settings["timezone"])
    now = now or datetime.now(timezone.utc)
    day = day or now.astimezone(tz).date()

    # Bước 1: thu thập
    window_start, window_end = filters.daily_window(day, settings)
    since = window_end - timedelta(hours=settings["dedup"]["cluster_window_hours"])
    fetch_cfg = settings["fetch"]
    ctx = fetcher.FetchContext(
        now=now, since=since, until=window_end,
        max_items=fetch_cfg["max_items_per_source"], max_summary_chars=fetch_cfg["max_summary_chars"],
        sitemap_known={s.id: store.sitemap_known_before(s.id, day) for s in sources_list if s.type == "sitemap"},
    )
    get = getter or fetcher.make_getter(storage.user_agent(settings), fetch_cfg["timeout_seconds"])
    results = fetcher.fetch_all(sources_list, ctx, get, fetch_cfg["max_workers"])
    n_ok = sum(r.ok for r in results)
    log(f"[1] Thu thập: {n_ok}/{len(results)} nguồn đọc được, {sum(len(r.articles) for r in results)} bài")
    for r in results:
        if not r.ok:
            log(f"    lỗi {r.source_id}: {r.error}")

    # Bước 2–3: lọc, gom sự kiện
    arts = [a for r in results for a in r.articles]
    arts = filters.prepare(arts, settings["dedup"]["strip_query_params"])
    arts = filters.within(arts, sources, since, window_end)
    arts, n_unconfirmed = filters.drop_unconfirmed_preprints(
        arts, sources, settings["scoring"]["preprint"]["confirmed_by_roles"])
    stories = filters.cluster(arts, sources, settings)
    stories, n_old, n_published = filters.select_new(
        stories, sources, window_start, window_end, store.load_seen(), day)
    log(f"[2-3] Lọc và gom: {len(stories)} sự kiện mới "
        f"(bỏ {n_unconfirmed} bài arXiv chưa xác nhận, {n_old} sự kiện cũ, {n_published} đã đăng)")

    # Bước 4–5: chấm điểm, phân mục
    kept, dropped = scorer.score_all(stories, sources, settings)
    classifier.classify_all(kept, sources, settings)
    n_imp = sum(s.label == "important" for s in kept)
    log(f"[4-5] Chấm điểm: giữ {len(kept)} tin ({n_imp} Quan trọng, {len(kept) - n_imp} Đáng chú ý), "
        f"loại {len(dropped)}")

    # Dịch
    report = translator.translate_stories(
        kept, settings, storage.load_glossary(), root,
        use_claude=use_claude, use_google=use_google, runner=runner, google=google,
        use_mymemory=use_mymemory, mymemory=mymemory, user_agent=storage.user_agent(settings))
    log(f"[dịch] {report.counts}" + (f" — Claude: {report.claude['error']}" if report.claude.get("error") else ""))

    # Bước 6: lưu JSON, lịch sử, trạng thái sitemap
    generated_at = now.astimezone(tz).isoformat(timespec="seconds")
    data = {
        "date": day.isoformat(),
        "generated_at": generated_at,
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "sources_status": [r.status_dict() for r in results],
        "stories": [s.to_dict() for s in kept],
        "translation": {"counts": report.counts},
    }
    json_path = store.save_daily(day, data)
    store.update_seen(day, [a.id for s in kept for a in s.articles])
    for r in results:
        if r.ok and r.sitemap_urls is not None:
            store.update_sitemap_state(r.source_id, day, r.sitemap_urls, baseline=ctx.sitemap_known.get(r.source_id) is None)

    # Bước 6: xuất HTML; vẽ lại cả hai ngày lân cận để cập nhật link "Ngày trước/Ngày sau"
    renderer = Renderer(ROOT / paths["templates_dir"], root / paths["docs_dir"], settings, all_sources)
    prev_day, next_day = store.neighbors(day)
    html_path = renderer.render_daily(data, prev_day, next_day)
    for other in (prev_day, next_day):
        other_data = store.load_daily(other) if other else None
        if other_data:
            renderer.render_daily(other_data, *store.neighbors(other))
    renderer.render_index(store)
    renderer.write_search_index(store)
    log(f"[6] Đã ghi {json_path.relative_to(root)} và {html_path.relative_to(root)}")

    # Nhật ký lượng dùng
    summary = {
        "generated_at": generated_at,
        "duration_seconds": round(time.monotonic() - started, 1),
        "sources_ok": n_ok,
        "sources_failed": [r.source_id for r in results if not r.ok],
        "stories": {"important": n_imp, "notable": len(kept) - n_imp, "dropped": len(dropped)},
        "translation": report.to_dict(),
    }
    usage_path = store.append_usage(day, summary)
    return DailyResult(day, json_path, html_path, usage_path, summary)


def _renderer(root: Path, settings: dict[str, Any]) -> Renderer:
    paths = settings["paths"]
    return Renderer(ROOT / paths["templates_dir"], root / paths["docs_dir"], settings,
                    storage.load_sources(include_disabled=True))


def run_summary(kind: str, day: date | None = None, root: Path = ROOT, now: datetime | None = None,
                log=print) -> Path:
    """Dựng bản tổng hợp: có `day` thì là kỳ chứa ngày đó, không có thì là kỳ vừa kết thúc."""
    settings = storage.load_settings()
    store = Storage(root / settings["paths"]["data_dir"])
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(settings["timezone"])).date()
    period = aggregator.period_for(kind, day) if day else aggregator.last_completed(kind, today)
    summary = aggregator.Aggregator(store, settings, now=now).build_and_save(period)
    renderer = _renderer(root, settings)
    html_path = renderer.render_summary_and_neighbors(store, kind, period.key)
    renderer.render_index(store)
    log(f"[{kind}] {period.key} ({period.start} → {period.end}): {summary['stats']['stories']} tin, "
        f"{len(summary['highlights'])} tin nổi bật → {html_path.relative_to(root)}")
    return html_path


def run_due(day: date | None = None, root: Path = ROOT, now: datetime | None = None, log=print) -> list[Path]:
    """Dựng mọi bản tổng hợp đến hạn vào ngày `day` (mặc định hôm nay theo giờ VN)."""
    settings = storage.load_settings()
    now = now or datetime.now(timezone.utc)
    day = day or now.astimezone(ZoneInfo(settings["timezone"])).date()
    kinds = aggregator.due_kinds(day)
    if not kinds:
        log(f"Ngày {day}: chưa đến hạn bản tổng hợp nào")
    # Kỳ vừa kết thúc tính theo ngày `day` (truyền ngày cuối của kỳ để dựng đúng kỳ đó)
    return [run_summary(k, aggregator.last_completed(k, day).end, root, now, log) for k in kinds]


def run_retranslate(day: date, root: Path = ROOT, log=print, **kwargs: Any) -> Path:
    """Dịch bù tin "chưa dịch" của một bản ngày đã lưu, rồi dựng lại trang ngày và các bản tổng hợp có ngày đó."""
    settings = storage.load_settings()
    store = Storage(root / settings["paths"]["data_dir"])
    data = store.load_daily(day)
    if data is None:
        raise SystemExit(f"Chưa có bản tin ngày {day}")
    kwargs.setdefault("user_agent", storage.user_agent(settings))
    report = translator.retranslate_daily(data, settings, storage.load_glossary(), root, **kwargs)
    store.save_daily(day, data)
    renderer = _renderer(root, settings)
    html_path = renderer.render_daily(data, *store.neighbors(day))
    renderer.write_search_index(store)
    renderer.render_index(store)
    log(f"[dịch bù] {day}: {report.counts}")
    # Bản tổng hợp đã có chứa ngày này: dựng lại để dùng bản dịch mới
    agg = aggregator.Aggregator(store, settings)
    for kind in aggregator.KINDS:
        period = aggregator.period_for(kind, day)
        if store.load_summary(kind, period.key) is not None:
            agg.build_and_save(period)
            renderer.render_summary_and_neighbors(store, kind, period.key)
            log(f"    dựng lại {kind} {period.key}")
    store.append_usage(day, {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "retranslate": True, "translation": report.to_dict()})
    return html_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bản tin AI & CNTT hằng ngày bằng tiếng Việt")
    p.add_argument("kind", choices=["daily", "weekly", "monthly", "quarterly", "yearly", "due", "retranslate"],
                   help="daily: bản ngày; weekly/monthly/quarterly/yearly: bản tổng hợp; "
                        "due: các bản tổng hợp đến hạn hôm nay; retranslate: dịch bù một bản ngày đã lưu")
    p.add_argument("--date", type=date.fromisoformat, default=None,
                   help="daily/due/retranslate: ngày (mặc định hôm nay theo giờ VN); "
                        "bản tổng hợp: một ngày bất kỳ trong kỳ (mặc định kỳ vừa kết thúc)")
    p.add_argument("--no-claude", action="store_true", help="không dịch bằng Claude (Google dịch thay)")
    p.add_argument("--no-google", action="store_true", help="không dùng Google Translate dự phòng")
    p.add_argument("--no-mymemory", action="store_true", help="không dùng MyMemory dự phòng")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    translate_opts = {"use_claude": not args.no_claude, "use_google": not args.no_google,
                      "use_mymemory": not args.no_mymemory}
    if args.kind in aggregator.KINDS:
        run_summary(args.kind, args.date)
        return 0
    if args.kind == "due":
        run_due(args.date)
        return 0
    if args.kind == "retranslate":
        if args.date is None:
            print("retranslate cần --date YYYY-MM-DD", file=sys.stderr)
            return 2
        run_retranslate(args.date, **translate_opts)
        return 0
    result = run_daily(args.date, use_claude=not args.no_claude, use_google=not args.no_google,
                       use_mymemory=not args.no_mymemory)
    print(f"Xong bản tin {result.day} trong {result.summary['duration_seconds']} giây.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
