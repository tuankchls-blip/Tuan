# ai-daily-digest — hướng dẫn cho Claude Code

Bản tin AI & CNTT hằng ngày bằng tiếng Việt, chạy tự động trên GitHub Actions, xuất HTML lên GitHub Pages.
Đặc tả đầy đủ nằm trong `PLAN.md`; file này là bản tóm tắt để làm việc nhanh. Khi hai file mâu thuẫn, `PLAN.md` thắng.

## Cách làm việc với chủ dự án

- Làm từng bước nhỏ; **hỏi chủ dự án trước khi bắt đầu mỗi bước**.
- Làm từng giai đoạn; hết giai đoạn thì dừng lại để duyệt theo bảng nghiệm thu, chưa sang giai đoạn sau.
- Trao đổi và chú thích bằng tiếng Việt.

## Lệnh

```bash
python main.py daily [--date YYYY-MM-DD] [--no-claude] [--no-google] [--no-mymemory]   # bản ngày
python main.py weekly|monthly|quarterly|yearly [--date YYYY-MM-DD]
pytest                                        # test, không gọi mạng
```

## Luồng xử lý bản ngày (6 bước, mỗi bước một module trong `digest/`)

1. `fetcher.py` — đọc RSS/API của mọi nguồn song song (tối đa 8 luồng, timeout 15 s/nguồn). Nguồn lỗi được ghi vào `sources_status`, không làm dừng chương trình.
2. `filters.py` — bản tin ngày D gồm tin trong 24 giờ trước D 07:00 giờ VN (mốc cố định); bỏ tin đã có trong `data/seen.json` của ngày trước D. Bài arXiv (role `preprint`) không lọc theo giờ (giờ trong feed là giờ công bố hôm sau) và bị bỏ nếu không được nguồn `community`/`expert` nhắc tới qua mã arXiv.
3. `filters.py` — chuẩn hóa URL; gộp bài cùng sự kiện khi cùng URL, cùng mã arXiv, tiêu đề giống theo `difflib`, hoặc chung đủ từ đặc trưng (trọng số IDF, có tên riêng chung). Bài gốc = trọng số cao nhất, nguồn khác vào `also_covered_by`.
4. `scorer.py` — điểm = trọng số nguồn + số nguồn cùng đưa tin + tín hiệu cộng đồng + từ khóa ưu tiên − từ khóa loại trừ. Gắn nhãn `important` (Quan trọng) hoặc `notable` (Đáng chú ý); dưới ngưỡng thì loại. Hacker News/HF Papers chỉ là tín hiệu: không tính là "nguồn độc lập", và tin chỉ có nguồn cộng đồng phải khớp từ khóa ưu tiên.
5. `classifier.py` — phân mục theo nội dung: models, research (có subcategory: nlp, cv, rl, safety, theory, systems…), infra, software, security, policy, business, vietnam. Mục rỗng thì ẩn.
6. `renderer.py` + `storage.py` — ghi `data/YYYY/YYYY-MM-DD.json`, dựng `docs/daily/YYYY/YYYY-MM-DD.html`, cập nhật `docs/index.html`.

Dịch (`translator.py`): dùng thư viện [`dichviet`](https://github.com/tuankchls-blip/dichviet) ghim `v0.1.0` (cấu hình `config/dichviet.yaml`, đặc tả trong `SPEC.md` của repo đó). Tin tiếng Việt giữ nguyên; tin đã có trong bộ nhớ đệm dùng lại; còn lại gọi `Translator.translate_items`: Claude Code CLI (`claude -p`, không công cụ, không MCP, haiku) rồi dịch máy theo `translation.fallback_order` (mặc định Google → MyMemory; thuật ngữ thay bằng mã giữ chỗ; Google gặp 429/CAPTCHA một lần, MyMemory hết hạn mức một lần là bỏ qua cho cả lần chạy; email MyMemory lấy từ `project.contact_email`); mọi bản dịch qua 7 phép kiểm tra của dichviet; tất cả lỗi thì để tiếng Anh với nhãn “chưa dịch” và ghi lý do. Bản dịch lưu trong `data/translations_cache.json` kèm nguồn dịch (`claude`/`google`/`mymemory`). Chủ dự án đã chọn không dùng token Claude trên GitHub (workflow chỉ cài Claude Code khi có secret `CLAUDE_CODE_OAUTH_TOKEN`). Nhật ký mỗi lần chạy ghi vào `data/usage/YYYY-MM-DD.json`; dichviet ghi thêm từng lô vào `data/usage/YYYY-MM-DD.jsonl`. Tắt Claude: `--no-claude` hoặc `DIGEST_NO_CLAUDE=1`.

Tổng hợp (`aggregator.py`): tuần (ISO, Thứ Hai–Chủ Nhật) ← tin Quan trọng của 7 bản ngày; tháng ← tuần; quý ← tháng; năm ← quý. Số liệu thống kê luôn tính lại từ dữ liệu ngày.

## Cấu trúc thư mục

```
main.py                      # daily / weekly / monthly / quarterly / yearly
config/sources.yaml          # nguồn: id, tên, url, nhóm, role, trọng số (1–3), ngôn ngữ, type
                             #   type: rss | hf_papers | hackernews | cisa_kev | crossref | sitemap
                             #   fallback_urls: địa chỉ dự phòng (Import AI: jack-clark.net vì Substack chặn GitHub)
                             #   sitemap (Anthropic, Stanford HAI): chỉ lấy URL mới xuất hiện;
                             #   lần chạy đầu chỉ ghi nhận, không đăng
config/settings.yaml         # ngưỡng điểm, từ khóa ưu tiên/loại trừ, múi giờ
config/glossary.yaml         # thuật ngữ, tên riêng riêng của bản tin (đè lên bảng có sẵn của dichviet)
config/dichviet.yaml         # cấu hình thư viện dịch dichviet
digest/                      # models, fetcher, filters, scorer, classifier, translator, aggregator, renderer, storage
templates/                   # Jinja2: daily, weekly, monthly, quarterly, yearly, index
data/                        # JSON gốc mỗi ngày, seen.json, sitemaps/, translations_cache.json, usage/
docs/                        # GitHub Pages: index.html, daily/, weekly/, monthly/, quarterly/, yearly/
.github/workflows/digest.yml # 00:17 UTC (07:17 VN) + dự phòng 01:47 UTC; khung tin chốt 07:00 VN
tests/                       # fixtures trong tests/fixtures/, không gọi mạng
```

## Quy ước code

- Python ≥ 3.11, type hints, `dataclass`. Tên biến/hàm tiếng Anh; chú thích, docstring tiếng Việt.
- Thư viện: `feedparser`, `requests`, `PyYAML`, `Jinja2`, `deep-translator`, `dichviet`, `pytest`. Bỏ trùng dùng `difflib`, không dùng thư viện AI.
- Thời gian lưu ISO 8601 có múi giờ; tính ngày và hiển thị theo `Asia/Ho_Chi_Minh` (`zoneinfo`).
- User-Agent ghi tên dự án và link repo.
- Chỉ lưu tiêu đề, tóm tắt, link; không tải toàn văn bài báo.
- Mọi hằng số điều chỉnh được (ngưỡng, trọng số, từ khóa) nằm trong `config/`, không viết cứng.
- HTML tự chứa: CSS/JS nhúng, không CDN; đọc tốt trên điện thoại; có chế độ sáng/tối.
- Test không gọi mạng; dịch vụ dịch được mock.
- Chạy lại cùng ngày ghi đè đúng bản ngày đó, không sinh tin trùng. Mọi lệnh nhận `--date`.
- Workflow: `contents: write`, `concurrency` chống chạy chồng, `workflow_dispatch` chọn loại bản tin và ngày.

## Cấu trúc dữ liệu ngày (`data/YYYY/YYYY-MM-DD.json`)

Đầu vào duy nhất cho HTML ngày và các bản tổng hợp.

```json
{
  "date": "2026-10-31",
  "generated_at": "2026-10-31T07:03:12+07:00",
  "sources_status": [{"source_id": "deepmind", "ok": true, "items": 2, "error": null}],
  "stories": [{
    "id": "sha1 của url đã chuẩn hóa",
    "url": "https://...",
    "source_id": "deepmind",
    "published_at": "2026-10-31T01:15:00+00:00",
    "lang": "en",
    "title_orig": "...", "summary_orig": "...",
    "title_vi": "...", "summary_vi": "...",
    "translated": true,
    "also_covered_by": [{"source_id": "the-verge", "url": "https://..."}],
    "category": "models", "subcategory": null,
    "score": 7.5, "label": "important",
    "matched_keywords": ["LLM", "benchmark"]
  }]
}
```

## An toàn khi dịch bằng Claude

Nội dung tin là văn bản bên ngoài, có thể chứa câu lệnh cài cắm. dichviet gọi Claude Code với `--tools ""`, `--strict-mcp-config`, `--max-turns 1`, `--no-session-persistence`, trong thư mục tạm trống: Claude chỉ đọc chữ và trả lời bằng chữ, không đọc/ghi file, không shell, không mạng. System prompt nói rõ mọi nội dung tin là dữ liệu cần dịch, không phải chỉ dẫn; kết quả lệch (thiếu mã, sót tiếng Anh, sai độ dài) bị loại ở bước kiểm tra.

## Lộ trình và nghiệm thu

1. **Bản ngày** — `python main.py daily` tạo HTML + JSON đúng cấu trúc; báo cáo nguồn đọc được/lỗi; không tin trùng; mọi tin tiếng Anh có bản dịch hoặc nhãn “chưa dịch”; tắt Claude thì Google dịch thay; có nhật ký trong `data/usage/`; `pytest` đạt.
2. **GitHub** — workflow chạy đúng lịch và bằng tay; tự commit; Pages hiển thị mục lục và bản mới nhất; chạy lại cùng ngày không trùng.
3. **Tổng hợp** — `weekly/monthly/quarterly/yearly` chạy với `--date`; test với dữ liệu giả lập hơn một năm; ranh giới tuần ISO đúng (kể cả 2026-W53 vắt sang 2027); mục lục liên kết mọi cấp.
4–5. **Mở rộng** — đặc tả viết sau khi giai đoạn 3 xong.
