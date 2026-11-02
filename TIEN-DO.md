# Theo dõi tiến độ

Một chỗ để chủ dự án theo dõi mọi việc đã làm trên **ai-daily-digest** (repo này) và thư viện dịch **dichviet** (repo `tuankchls-blip/dichviet`), qua mọi phiên Claude Code.

**Quy tắc:** xong mỗi giai đoạn (hoặc một bước lớn, một PR) thì cập nhật file này: bảng trạng thái, nhật ký theo ngày, việc đang chờ. Ghi ngắn, có link PR/commit để tra cứu. Ngày theo giờ Việt Nam.

Cập nhật lần cuối: 02/11/2026.

## Trạng thái hiện tại

### ai-daily-digest

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| 1 | Bản ngày: thu thập 31 nguồn, lọc, gộp sự kiện, chấm điểm, phân mục, dịch, HTML | Xong (30/10) |
| 2 | GitHub Actions chạy lịch 07:17 VN, tự commit, GitHub Pages | Xong (30/10, chỉnh 02/11) |
| 3 | Bản tổng hợp tuần, tháng, quý, năm; lệnh `due`, `retranslate` | Xong, đã duyệt (02/11) |
| — | Chuyển phần dịch sang thư viện dichviet | Đang làm: PR [#1](https://github.com/tuankchls-blip/Tuan/pull/1), chờ quyết định (xem "Đang chờ") |
| 4 | AI qua GitHub Models: dịch bằng AI, nhận định bằng lời | Đã viết đặc tả trong `PLAN.md` (02/11), chưa làm |
| 5 | App iOS (PWA), trang phân tích dữ liệu | Đã viết đặc tả trong `PLAN.md` (02/11), chưa làm |

### dichviet

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| 1 | Văn bản thường, Markdown, JSON; claude-cli, dự phòng Google rồi MyMemory | Xong: bản `v0.1.0` (02/11), [Release](https://github.com/tuankchls-blip/dichviet/releases/tag/v0.1.0); nghiệm thu 7/8 mục trong `review/nghiem-thu-gd1.md` của repo dichviet |
| 2 | Bài báo khoa học: HTML, Word, PDF giữ bố cục, LaTeX; hồ sơ học thuật | Chưa làm |
| 3 | PDF scan, phụ đề, mô hình chạy cục bộ | Chưa làm |

## Đang chờ chủ dự án

1. **Chuyển repo `dichviet` sang public.** Repo đang private nên GitHub Actions của repo này không cài được `dichviet` → CI của PR #1 đỏ. SPEC ghi đây là repo công khai.
2. **Chọn cách ghép dichviet với giai đoạn 4.** Đặc tả giai đoạn 4 (viết ở phiên khác) đưa dịch bằng GitHub Models vào `translator.py` cũ (dùng lại skill `dich-tin-ai`, `read_output`), trong khi PR #1 thay `translator.py` bằng dichviet và bỏ các phần đó.
3. **`translation.max_lost_terms`** (phiên khác thêm 02/11: dịch máy mất tối đa 1 thuật ngữ vẫn nhận): dichviet hiện coi thiếu mã giữ chỗ là lỗi cứng, chưa có tùy chọn này.

## Nhật ký

Có hai phiên Claude Code làm song song; mỗi mục ghi phiên để tra cứu:
- **Phiên A** (`session_0196SPMvMwxfh2fcujzvXB6u`): xây ai-daily-digest giai đoạn 1–3, đặc tả 4–5.
- **Phiên B** (`session_0196SPMt56PcBbhBgmrrVyrn`): hướng dẫn token Claude, xây dichviet, tích hợp dichviet vào bản tin.

### 30/10/2026

- **Phiên A — ai-daily-digest giai đoạn 1–2.** `PLAN.md`, `CLAUDE.md`; cấu hình 31 nguồn, thuật ngữ, skill `dich-tin-ai`; lõi bản tin (thu thập, lọc, gộp, chấm điểm, phân mục); dịch bằng Claude Code (đọc `in.json`, ghi `out.json`) với Google dự phòng; HTML và `main.py daily`; workflow GitHub Actions hằng ngày và chạy test; chỉ cài Claude Code khi có token. Commit `d626f2b` → `add2ad4`.
- **Phiên B.** Hướng dẫn tạo token bằng `claude setup-token` và lưu secret `CLAUDE_CODE_OAUTH_TOKEN`. Chủ dự án sau đó chọn không dùng token Claude trên GitHub.
- Bản tin tự động đầu tiên: 30/10.

### 31/10/2026

- **Phiên B.** Chủ dự án tạo repo `dichviet` và đưa `SPEC.md` lên.
- Bản tin tự động 31/10.

### 01/11/2026

- Bản tin tự động 01/11.

### 02/11/2026

- **Phiên A — dịch dự phòng và lịch chạy.** MyMemory làm máy dự phòng thứ hai (Google bị chặn trên GitHub), địa chỉ dự phòng cho nguồn, feed trống không còn là lỗi; giờ chạy 07:17 VN, lịch dự phòng 08:47. Commit `f5c19d6`, `829197f`.
- **Phiên A — giai đoạn 3 (đã duyệt).** `aggregator.py`: bản tổng hợp tuần/tháng/quý/năm và trang HTML; lệnh `due` (tự tạo bản tổng hợp đến hạn), `retranslate` (dịch bù tin "chưa dịch"); `translation.max_lost_terms`. Commit `0811ec2` → `831d241`.
- **Phiên A — đặc tả giai đoạn 4–5** trong `PLAN.md`: AI qua GitHub Models (dịch, nhận định), PWA cho iPhone, trang phân tích. Commit `a695bda`.
- **Phiên B — dichviet giai đoạn 1 → `v0.1.0`.** Thư viện Python + lệnh `dichviet`: văn bản thường, Markdown, JSON; claude-cli (`claude -p`, không công cụ, không MCP), dự phòng Google rồi MyMemory; 7 phép kiểm tra, bộ nhớ đệm, nhật ký; 101 test không gọi mạng; bộ 40 câu mẫu chủ dự án đã duyệt (40/40 đạt, 5/5 lần chạy). Sửa trong lúc nghiệm thu: quy tắc phủ định "không"/"chưa" trong system prompt; MyMemory làm hỏng mã giữ chỗ `⟦P1⟧` nên đổi sang dạng `ZXP1XZ`. PR [dichviet#1](https://github.com/tuankchls-blip/dichviet/pull/1) merge, Release `v0.1.0`.
- **Phiên B — tích hợp dichviet vào bản tin** (PR [#1](https://github.com/tuankchls-blip/Tuan/pull/1), chưa merge):
  - Bước 1: `requirements.txt` ghim `dichviet@v0.1.0`, `config/dichviet.yaml`; "inference" giữ nguyên tiếng Anh; bỏ 7 mục thuật ngữ lệch với dichviet.
  - Bước 2: `translator.py` gọi dichviet; giữ bộ nhớ đệm theo tin, nhãn "chưa dịch", các cờ `--no-*`; email MyMemory lấy từ `project.contact_email`.
  - Bước 3: workflow, `CLAUDE.md`, `README.md`, ghi chú `PLAN.md`; xóa skill `dich-tin-ai` và `data/translate/in.json`.
  - Chạy thử thật trên bản sao repo: 31/31 nguồn, 10 tin, Claude dịch 7/7 tin.
  - CI đỏ vì repo dichviet private; PR được tạo từ `main` cũ, nay xung đột với giai đoạn 3 (lệnh `retranslate`, `max_lost_terms`) và đặc tả giai đoạn 4 → chờ quyết định.
- Bản tin tự động 02/11 (daily, weekly, monthly, retranslate).
