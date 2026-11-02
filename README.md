# ai-daily-digest — Bản tin AI & CNTT hằng ngày

Mỗi ngày, chương trình gom tin mới trong 24 giờ qua từ 31 nguồn uy tín về AI, khoa học máy tính và CNTT, chọn ra mọi tin đủ quan trọng theo góc nhìn nhà nghiên cứu, dịch sang tiếng Việt và xuất thành trang HTML đọc được trên điện thoại.

Đặc tả đầy đủ: [`PLAN.md`](PLAN.md). Tiến độ từng phiên làm việc: [`TIEN_DO.md`](TIEN_DO.md). Tóm tắt cho Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Cài đặt trên máy

Cần Python 3.11 trở lên.

```bash
git clone https://github.com/tuankchls-blip/Tuan.git
cd Tuan
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Dịch:** nếu máy có [Claude Code](https://code.claude.com) đã đăng nhập, chương trình gọi lệnh `claude` để dịch, với quyền tối thiểu (chỉ đọc file tin cần dịch và ghi file kết quả, không chạy lệnh, không truy cập mạng). Không có Claude thì dịch máy dự phòng: Google Translate, rồi MyMemory (miễn phí, 50.000 ký tự/ngày). Google hay chặn máy chủ trung tâm dữ liệu (kể cả GitHub Actions) bằng CAPTCHA. Khi mọi cách đều lỗi, tin hiện tiếng Anh với nhãn “chưa dịch” và được dịch lại ở lần chạy sau.

## Chạy

```bash
python main.py daily                      # bản tin hôm nay (giờ Việt Nam)
python main.py daily --date 2026-10-30    # tạo lại bản của một ngày
python main.py daily --no-claude          # chỉ dịch máy (Google, MyMemory)
python main.py daily --no-claude --no-google --no-mymemory   # không dịch (để kiểm tra nhanh)

python main.py weekly                     # bản tuần vừa kết thúc (tương tự monthly, quarterly, yearly)
python main.py weekly --date 2026-10-28   # bản tuần chứa ngày 28/10 (tuần 2026-W44)
python main.py due                        # mọi bản tổng hợp đến hạn hôm nay
python main.py retranslate --date 2026-10-30   # dịch bù tin "chưa dịch" của một bản ngày đã lưu
```

Bản tổng hợp: tuần (Thứ Hai – Chủ Nhật, theo tuần ISO), tháng, quý, năm. Mỗi cấp chọn tin nổi bật từ cấp ngay dưới; số liệu luôn tính lại từ dữ liệu ngày. Lưu ở `data/<weekly|monthly|quarterly|yearly>/` và `docs/<weekly|monthly|quarterly|yearly>/`.

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

## Chạy tự động trên GitHub

Workflow `.github/workflows/digest.yml` tạo bản tin mỗi sáng lúc 07:17 giờ Việt Nam (lịch dự phòng 08:47, tự bỏ qua nếu bản hôm nay đã có), tạo thêm các bản tổng hợp đến hạn (bản tuần sáng Thứ Hai, bản tháng ngày 1, bản quý đầu quý, bản năm ngày 1/1), commit `data/` và `docs/` vào nhánh `main`, rồi GitHub Pages đăng lại trang:

**https://tuankchls-blip.github.io/Tuan/**

GitHub có thể chạy lịch trễ vài chục phút đến vài giờ; nội dung không đổi vì khung tin luôn chốt lúc 07:00.

**Chạy tay, tạo lại một ngày hoặc dịch bù:** tab *Actions* → *Bản tin AI hằng ngày* → *Run workflow*, chọn loại (`daily`, `weekly`…, `due`, `retranslate`), nhập ngày.

Cài đặt một lần trong *Settings* của repo (đã làm):

1. *General* → *Default branch*: `main`.
2. *Actions* → *General* → *Workflow permissions*: **Read and write permissions**.
3. *Pages* → *Deploy from a branch*: `main`, thư mục `/docs`.
4. (Tùy chọn) *Secrets and variables* → *Actions*: secret `CLAUDE_CODE_OAUTH_TOKEN` (tạo bằng `claude setup-token`) để dịch bằng Claude. Không có secret thì dịch bằng Google, rồi MyMemory.

Workflow `.github/workflows/tests.yml` chạy `pytest` mỗi khi đẩy code.

## Kiểm thử

```bash
pytest
```

Test dùng dữ liệu mẫu trong `tests/fixtures/`, không gọi mạng; Claude và Google đều được giả lập.

## Lộ trình

1. **Bản ngày** (xong)
2. **Chạy tự động trên GitHub Actions + GitHub Pages** (xong)
3. **Bản tổng hợp** tuần, tháng, quý, năm (xong)
