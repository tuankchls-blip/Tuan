# Tiến độ dự án ai-daily-digest

Tài liệu theo dõi cho chủ dự án: mỗi giai đoạn xong (hoặc khi có quyết định quan trọng) Claude cập nhật file này.
Đặc tả: [`PLAN.md`](PLAN.md) · Hướng dẫn dùng: [`README.md`](README.md) · Trang bản tin: https://tuankchls-blip.github.io/Tuan/

## Tổng quan

| Giai đoạn | Nội dung | Trạng thái | Ngày duyệt |
| --- | --- | --- | --- |
| 1 | Bản ngày: thu thập 31 nguồn, lọc, gộp sự kiện, chấm điểm, phân mục, dịch, xuất HTML | ✅ Xong | 30/10/2026 |
| 2 | Chạy tự động trên GitHub Actions, đăng GitHub Pages | ✅ Xong | 02/11/2026 |
| 3 | Bản tổng hợp tuần, tháng, quý, năm | ✅ Xong | 02/11/2026 |
| 4 | AI qua GitHub Models: dịch tốt hơn, nhận định bằng lời | 🔄 Đang làm (bước 1) | |
| 5 | App iOS dạng PWA (đọc offline, lưu tin, thông báo đẩy), trang phân tích dữ liệu | ⏳ Chưa làm | |

**Việc đang chờ chủ dự án:** chạy dịch bù `retranslate` cho ngày 31/10 (58 tin) và 30/10 (1 tin): *Actions → Bản tin AI hằng ngày → Run workflow*. Để sang ngày khác nhau vì hạn mức MyMemory 50.000 ký tự/ngày.

---

## Phiên 1 · 30/10/2026 — Giai đoạn 1 và khởi động giai đoạn 2

### Đã làm

1. **Khởi tạo:** lưu tài liệu kế hoạch thành `PLAN.md`, tạo `CLAUDE.md` (tóm tắt cho Claude Code). Dự án đặt ở gốc repo `tuankchls-blip/Tuan`.
2. **Kiểm tra 31 nguồn** (sau khi chủ dự án mở quyền mạng cho phiên cloud):
   - 24 nguồn đọc RSS/Atom trực tiếp.
   - 4 nguồn qua API JSON: HF Daily Papers, Hacker News (Algolia), CISA KEV, CACM qua Crossref (`cacm.acm.org` chặn 403, ACM DL không có RSS).
   - 2 nguồn không có RSS, dùng sitemap: Anthropic, Stanford HAI (chỉ đăng URL mới; lần đầu chỉ ghi nhận).
   - Meta AI dùng `engineering.fb.com` vì `ai.meta.com` không có RSS.
3. **Cấu hình:** `config/sources.yaml`, `settings.yaml`, `glossary.yaml`, skill dịch `.claude/skills/dich-tin-ai/SKILL.md`.
4. **Phần lõi** (`digest/`): thu thập song song, lọc 24 giờ (mốc cố định 07:00 VN), gộp sự kiện, chấm điểm, phân mục.
   - Gộp sự kiện bằng `difflib` không bắt được tin cùng sự kiện viết khác nhau → thêm cách so “từ đặc trưng chung” có trọng số IDF (thử thật: 6/6 cặp đúng, 0 nhầm).
   - arXiv ~1.500 bài/ngày: không lọc theo giờ (giờ trong feed là hôm sau), chỉ giữ bài được HF Papers/HN/blog chuyên gia nhắc tới.
   - Hacker News chỉ là tín hiệu: không tính là nguồn độc lập; tin chỉ có HN phải khớp từ khóa.
5. **Dịch:** Claude Code gọi từ Python với quyền tối thiểu (chỉ đọc/ghi đúng 4 file) → Google dự phòng → nhãn “chưa dịch”.
6. **Xuất HTML:** bản ngày + mục lục, tự chứa (không CDN), sáng/tối, bộ lọc, tìm kiếm, nội dung feed luôn được thoát ký tự.
7. **Chỉnh chọn tin theo yêu cầu:** thêm từ khóa bảo mật, ngưỡng báo AI 3, bài lab thường kỳ không tự động Quan trọng, HF Papers cần ≥ 5 phiếu.
8. **Giai đoạn 2 bắt đầu:** workflow `digest.yml` + `tests.yml`, tạo nhánh `main`. Chủ dự án cài đặt GitHub (nhánh mặc định, quyền ghi, Pages). Lần chạy tay đầu tiên thành công.

### Quyết định của chủ dự án

- Gọi Claude ngay trong Python thay vì bước workflow riêng.
- Dùng email `tuankch.ls@gmail.com` trong User-Agent (Crossref khuyến nghị).
- **Không dùng token Claude trên GitHub** → dịch bằng Google, sau đó MyMemory.

### Sự cố và bài học

- Lỡ gọi Claude CLI thật một lần khi kiểm tra (~0,49 USD quy đổi); lần đó lộ lỗi quyền ghi file (`Write(...)` phải là `Edit(...)`), đã sửa và thử lại có chủ đích (~0,05 USD). Tổng ~0,54 USD.
- Google Translate chặn IP máy chủ (cả phiên cloud lẫn GitHub) bằng CAPTCHA.
- Lỡ commit file `actionlint_py-*.tar.gz`, đã xóa và thêm `.gitignore`.

---

## Phiên 2 · 02/11/2026 — Hoàn tất giai đoạn 2 và 3, đặc tả giai đoạn 4–5

### Giai đoạn 2 (hoàn tất)

- Lịch chạy 31/10, 01/11, 02/11 đều thành công nhưng **trễ ~5 tiếng** (00:00 UTC là giờ cao điểm) → đổi sang 07:17 VN, thêm lịch dự phòng 08:47 (tự bỏ qua nếu bản hôm nay đã có).
- Google bị chặn trên GitHub → thêm **MyMemory** (miễn phí, 50.000 ký tự/ngày, tự viết lời gọi có timeout). Thử thật: 7/7 tin được dịch.
- Import AI bị Substack chặn trên GitHub → thêm địa chỉ dự phòng `jack-clark.net` (`fallback_urls`).
- arXiv cuối tuần feed trống không còn bị báo lỗi.
- Nghiệm thu: chạy đúng lịch ✅, chạy tay ✅, tự commit ✅, Pages hiển thị ✅ (chủ dự án xác nhận), chạy lại cùng ngày không trùng ✅.

### Giai đoạn 3 (hoàn tất)

- `digest/aggregator.py`: tuần ISO (kể cả 2026-W53 vắt sang 2027), tháng, quý, năm; tin nổi bật chọn từ cấp ngay dưới; số liệu luôn tính từ dữ liệu ngày; chủ đề tăng/giảm, sự kiện nhiều ngày, nghiên cứu đáng đọc, xu hướng, dòng thời gian.
- Trang HTML cho 4 cấp, link kỳ trước/sau, mục lục liên kết mọi cấp.
- Lệnh mới: `weekly|monthly|quarterly|yearly [--date]`, `due` (workflow gọi sau bản ngày), `retranslate --date` (dịch bù bản ngày đã lưu).
- Chạy thật trên GitHub: bản tuần 2026-W44, bản tháng 10/2026, dịch bù 30/10 (47/48 tin) và 01/11 (13/13).
- Theo yêu cầu: bản dịch máy mất tối đa 1 thuật ngữ vẫn được nhận (`translation.max_lost_terms`).
- 108 test, không test nào gọi mạng.

### Đặc tả giai đoạn 4–5 (đã duyệt)

Quyết định của chủ dự án: AI dùng **GitHub Models** (miễn phí); nhận định ở cả bản ngày và bản tổng hợp; app iOS dạng **PWA**; thêm trang phân tích dữ liệu. Chi tiết và bảng nghiệm thu: `PLAN.md` › “Đặc tả giai đoạn 4–5”.

---

## Theo dõi chi phí và hạn mức

| Dịch vụ | Dùng cho | Hạn mức / chi phí | Ghi chú |
| --- | --- | --- | --- |
| GitHub Actions | Chạy bản tin hằng ngày | Miễn phí (repo công khai) | ~20 giây/lần chạy |
| MyMemory | Dịch dự phòng | 50.000 ký tự/ngày (miễn phí) | Ngày nhiều tin ~30.000 ký tự |
| Google Translate | Dịch dự phòng | Bị chặn trên GitHub | Vẫn thử 3 lần rồi bỏ qua |
| Claude (gói của chủ dự án) | Không dùng trên GitHub | ~0,54 USD đã dùng khi kiểm tra ở phiên 1 | Bật lại bằng secret `CLAUDE_CODE_OAUTH_TOKEN` |
| GitHub Models | Giai đoạn 4 | Miễn phí trong hạn mức ngày | Đang kiểm tra |
