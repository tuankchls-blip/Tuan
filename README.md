# ai-daily-digest — Bản tin AI & CNTT hằng ngày

Mỗi ngày, chương trình gom tin mới trong 24 giờ qua từ 31 nguồn uy tín về AI, khoa học máy tính và CNTT, chọn ra mọi tin đủ quan trọng theo góc nhìn nhà nghiên cứu, dịch sang tiếng Việt và xuất thành trang HTML đọc được trên điện thoại.

Đặc tả đầy đủ: [`PLAN.md`](PLAN.md). Tóm tắt cho Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Cài đặt trên máy

Cần Python 3.11 trở lên.

```bash
git clone https://github.com/tuankchls-blip/Tuan.git
cd Tuan
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Dịch bằng Claude (khuyến nghị):** cài [Claude Code](https://code.claude.com) và đăng nhập bằng gói Claude của bạn. Chương trình tự gọi lệnh `claude` để dịch, với quyền tối thiểu (chỉ đọc file tin cần dịch và ghi file kết quả, không chạy lệnh, không truy cập mạng). Nếu không có Claude, chương trình dịch dự phòng bằng Google Translate. Lưu ý: Google đôi khi chặn máy chủ trung tâm dữ liệu bằng CAPTCHA; khi cả hai cách đều lỗi, tin hiện tiếng Anh với nhãn “chưa dịch” và được dịch lại ở lần chạy sau.

## Chạy

```bash
python main.py daily                      # bản tin hôm nay (giờ Việt Nam)
python main.py daily --date 2026-10-30    # tạo lại bản của một ngày
python main.py daily --no-claude          # chỉ dịch bằng Google
python main.py daily --no-claude --no-google   # không dịch (để kiểm tra nhanh)
```

Kết quả:

| File | Nội dung |
| --- | --- |
| `docs/daily/YYYY/YYYY-MM-DD.html` | Trang bản tin của ngày, mở trực tiếp bằng trình duyệt |
| `docs/index.html` | Mục lục: bản mới nhất, mọi bản đã lưu, ô tìm kiếm theo tiêu đề |
| `data/YYYY/YYYY-MM-DD.json` | Dữ liệu gốc của ngày (đầu vào cho bản tuần/tháng/quý/năm) |
| `data/usage/YYYY-MM-DD.json` | Nhật ký mỗi lần chạy: thời gian, số tin, cách dịch, token và chi phí Claude báo về |

Bản tin ngày D gồm tin trong 24 giờ trước 07:00 sáng ngày D (giờ Việt Nam). Chạy lại cùng ngày thì ghi đè đúng bản của ngày đó, không sinh tin trùng. Lưu ý: feed chỉ giữ tin gần đây, nên tạo lại một ngày quá xa trong quá khứ sẽ thiếu tin.

Lần chạy đầu, hai nguồn không có RSS (Anthropic, Stanford HAI) chỉ ghi nhận các bài hiện có; từ lần sau mới đăng bài mới.

## Chỉnh cách chọn tin

Không cần sửa code, chỉ sửa file trong `config/`:

- `config/sources.yaml`: thêm, bỏ, tắt nguồn (`enabled: false`), đổi trọng số.
- `config/settings.yaml`: ngưỡng điểm, từ khóa ưu tiên và loại trừ, quy tắc phân mục, cấu hình dịch.
- `config/glossary.yaml`: thuật ngữ và tên riêng giữ nguyên khi dịch.

Mỗi tin trong file JSON ngày có trường `reasons` giải thích vì sao tin được chọn hoặc bị loại, giúp chỉnh cấu hình.

## Kiểm thử

```bash
pytest
```

Test dùng dữ liệu mẫu trong `tests/fixtures/`, không gọi mạng; Claude và Google đều được giả lập.

## Lộ trình

1. **Bản ngày** (xong, chờ duyệt)
2. **Chạy tự động trên GitHub Actions + GitHub Pages** — hướng dẫn bật Actions và Pages sẽ được bổ sung ở đây. Hiện workflow dịch bằng Google Translate; muốn dịch bằng Claude thì thêm secret `CLAUDE_CODE_OAUTH_TOKEN` (tạo bằng `claude setup-token`), workflow sẽ tự dùng.
3. **Bản tổng hợp** tuần, tháng, quý, năm.
