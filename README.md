# English Graded Reader

Trình đọc tin tiếng Anh theo trình độ cho Nhung (mục tiêu B1+): kinh doanh, du lịch,
thời trang, viết lại theo đúng vốn từ của người đọc, kèm đọc to giọng Mỹ.
Một trang HTML tĩnh, chạy được từ `file://` và GitHub Pages, không gọi tài nguyên ngoài.

- **Đọc:** https://david-fn-adv.github.io/english-reader/
- **Kiểm tra vốn từ:** https://david-fn-adv.github.io/english-reader/test/

Đặc tả gốc: `english-reader-spec.md` (v1, 2026-10-14). Kiến trúc mượn từ reader tiếng
Trung (`david-fn-adv/Chinese`), không dùng chung mã.

| | Trạng thái |
|---|---|
| Phase 1 — bài kiểm tra vốn từ | xong: `test/index.html`, `data/bands.json`, `tools/seed_known.py` |
| Phase 2 — khung reader + 1 bài mẫu | xong, đã duyệt 2026-10-15 |
| Phase 3 — pipeline hằng ngày | công cụ xong, `selftest.py` PASS; **chờ Dương soát bài thật đầu tiên rồi mới bật lịch** |

## Dùng

1. **Làm bài kiểm tra:** mở `test/index.html` (điện thoại được, offline được). 160 từ,
   khoảng 15 phút. Cuối bài bấm **Tải kết quả (.json)**.
2. **Gieo tập từ đã biết:**
   ```bash
   python tools/seed_known.py ~/Downloads/vocab-test-2026-10-20.json
   # ghi đè ngưỡng (quyết định của người, không phải của pipeline):
   # python tools/seed_known.py RESULT.json --threshold 3 --reason "…"
   python tools/patch_app.py news/2026-10-14.json     # nhúng lại known vào index.html
   ```
3. **Đọc:** mở `index.html`. Bấm từ nào cũng mở thẻ tra; ▶ cạnh mỗi đoạn để nghe.
4. **Tập từ lớn dần:** trong Kho từ bấm **Xuất known.json**, đưa file vào `known/`, rồi
   ```bash
   python tools/seed_known.py --merge known/known-export-2026-11-02.json
   ```

> **Tập từ hiện tại** (`known/known.json`) gieo từ bài kiểm tra của Nhung ngày 2026-10-15
> (`known/history/vocab-test-2026-10-15.json`): ước lượng ≈ 5.250 từ, bấm nhầm từ giả 3%.
> Quy tắc của test cho ngưỡng 1 — mức 2 và 3 đạt 13/16, thiếu đúng một từ mỗi mức để chạm
> 80% — nên Dương quyết định **ghi đè ngưỡng = 3, frontier = 4** (`--threshold 3`). Giá trị gốc
> của test và lý do nằm trong `known.json` → `threshold_override`.

## Cài đặt

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; Linux/macOS: .venv/bin/python
.venv/Scripts/python -m spacy download en_core_web_sm
```

`numpy==2.5.1` được ghim chỉ vì máy dev chạy Windows Application Control, chặn DLL của
các bản numpy mới hơn. Máy khác dùng numpy nào cũng được.

## Cấu trúc

```
index.html              reader + dữ liệu nhúng trong <script id="data">
test/index.html         bài kiểm tra vốn từ (danh sách từ nhúng sẵn, chạy offline)
test/items.v1.json      160 câu: 128 từ thật (16 × mức 1–8) + 32 từ giả, thứ tự cố định
data/bands.json         lemma -> mức tần suất 1..10 (10.000 lemma)
data/pseudowords.json   44 từ giả viết tay (chọn 32)
data/loanwords.json     từ mượn quốc tế / từ có gốc chung với tiếng Việt
data/phrases.json       cụm từ nhiều chữ, so theo chuỗi lemma
known/known.json        tập từ đã biết hiện tại
known/history/          các file kết quả kiểm tra
news/YYYY-MM-DD.json    một bài một file
news/drafts/            bản nháp đầu vào của build_article.py
tools/                  script Python (xem dưới)
```

| Script | Việc |
|---|---|
| `build_bands.py` | dựng `data/bands.json` từ wordfreq (chạy một lần, ~6 phút) |
| `make_test_items.py` | dựng `test/items.v1.json` và nhúng vào `test/index.html` |
| `seed_known.py` | kết quả test → `known/known.json`; `--merge` gộp file xuất từ app |
| `coverage.py` | cổng độ phủ (spec §4.4) |
| `gloss.py` | mục từ điển cho từ chưa có; `--check` kiểm cả định nghĩa tiếng Anh có đọc được không |
| `build_article.py` | ráp `news/<ngày>.json` khi hai cổng trên đều đạt |
| `patch_app.py` | gộp một bài vào `index.html`, idempotent |
| `qa.py` (+ `qa_render.js`) | render bằng jsdom, bấm mọi token, không lỗi console |
| `frontier.py` | danh sách từ mục tiêu / từ ôn lại khi viết nháp |
| `selftest.py` | chạy toàn bộ trên bản sao repo, có cả bài hỏng — chạy trên mọi máy mới |
| `daily-news.md` | **hợp đồng** cho tác vụ Cowork — thắng mọi prompt |
| `enlib.py` | hàm dùng chung (IPA, tách từ, tập đã biết) |

## Quyết định cần biết

**Lọc danh từ riêng khi dựng mức tần suất.** wordfreq không giữ chữ hoa nên không so được
"Paris" với "paris". Thay vào đó dùng ba tín hiệu: spaCy gắn PROPN trong 5 câu đệm viết
thường, NER bắt được trong 2 câu đệm viết hoa, và tần suất gần bằng nhau ở 9 ngôn ngữ khác
(tên riêng viết giống nhau ở mọi nơi). Quy tắc thiên về *giữ*: một tên lọt vào mức chỉ tốn
một chỗ, còn một từ thật bị loại thì về sau cổng độ phủ sẽ coi là "vượt cấp". Chi tiết và
ngưỡng ở đầu `tools/build_bands.py`. Vài tên còn lọt (robinson, denmark, birmingham…);
danh sách câu hỏi kiểm tra đã được rà tay để loại chúng.

**Lemma.** Mỗi từ được chạy qua bộ lemma của spaCy với POS ép lần lượt VERB → NOUN → ADJ
(wore → wear, children → child). `LEMMA_FIX` trong `enlib.py` sửa vài lemma vô ích cho người
học (data → datum) và được dùng chung khi dựng mức và khi tách từ bài đọc, nên hai bên khớp nhau.

**Bổ sung vào schema của spec** (đều là trường tuỳ chọn, thêm vào, không đổi trường cũ):

- token `nsp: 1` — không có khoảng trắng sau token này (`U.S.,` · `6.8%`). Cần để dựng lại
  câu đúng cho TTS và để hiển thị.
- `names[x].full` — tên nhiều chữ ("Statistics Canada") để thẻ tra hiện đủ tên.
- file bài có thêm `dict` và `names`; `patch_app.py` chuyển chúng vào bảng chung của payload.
- `source.author`, `source.title`, `source.accessed`.
- payload có thêm `known` (tập đã biết gốc, cần để app tính trạng thái mặc định và xuất
  known.json) và `meta.band_size` / `meta.band_known` cho biểu đồ Tiến độ.
- `known.json` có thêm `history` (vẽ biểu đồ vốn từ), `app_known` (từ đánh dấu Đã biết
  trong app — được giữ lại khi làm lại bài kiểm tra) và `threshold_override` (khi người
  quyết định khác ngưỡng của test).

**Từ điển phủ mọi từ, không chỉ từ mới.** Spec §4.5 nói gloss cho từ `core` và cụm từ, nhưng
§4.7 (qa) đòi mọi token có mục từ điển. `gloss.py` sinh mục cho **mọi lemma chưa có** trong từ
điển của app; từ điển tích luỹ nên bài sau cần ít mục mới hơn. Từ điển chuẩn là payload trong
`index.html`; file bài chỉ mang mục mới.

**Từ ôn lại** (spec §4.3, 3–5 từ core của 3 bài trước) vẫn được tô như từ mới nhưng **tính là
quen** khi đo độ phủ và không tính vào 8–12 từ mới — nếu không, ba yêu cầu (≥ 95%, 8–12 mới,
3–5 ôn) gần như không thể cùng đạt.

**Gửi bài muốn đọc** mở issue GitHub theo mẫu `.github/ISSUE_TEMPLATE/request.yml` (nhãn
`request`); Nhung cần tài khoản GitHub.

**Cổng tách câu.** spaCy không ngắt câu sau từ viết tắt có dấu chấm ("…a visit to the
U.S. September was…" thành một câu), làm hỏng phần tô sáng của TTS và câu ví dụ trong thẻ tra.
`build_article.py` báo lỗi khi gặp trường hợp đó; người viết đổi cách diễn đạt.

**Giới hạn đã biết của quy tắc phụ tố** (spec §4.4): `re-`/`un-` đôi khi đoán sai — `recover`
bị tính là "re + cover" nên được coi là đã biết. Cần xem lại ở Phase 3.

## Kết quả kiểm thử (Phase 1–2)

- `data/bands-sanity.txt`: số từ và 20 từ mẫu mỗi mức (mức 1–2: *find, help, agree*…;
  mức 8: *marginal, intervene, milestone*…). `garrison` mức 8, `exquisite` mức 9.
- Chấm điểm bài kiểm tra: toàn "Biết" → `reliable: false`; toàn "Không biết" → threshold 0;
  mẫu trả lời kiểu B1 → threshold 2.
- `seed_known.py` với kết quả threshold 2 → 2.000 lemma + 31 từ biết thêm.
- Bài mẫu qua cổng: 414 từ, câu trung bình 13,4 từ, dài nhất 25, độ phủ hiệu dụng 0,956,
  8 từ mới mức 4 (mỗi từ 2 lần), 17 số liệu đều có dòng nguồn.
- Reader: 399/399 token mở thẻ có nghĩa; TTS tô câu + tô từ (onboundary); tắt TTS vẫn hiển
  thị; ẩn nghĩa; trạng thái từ giữ sau khi tải lại; không tràn ngang ở 320 px.
- `patch_app.py` chạy 3 lần → `index.html` giống nhau từng byte.
- Xuất known.json → `seed_known.py --merge` hai lần → file giống nhau, không trùng mục.
- **Chưa thử trên iPhone Safari thật** — cần Nhung mở thử.

## Bản quyền

Bài đọc là bản viết lại đơn giản hoá, không phải bản dịch; mỗi bài ghi nguồn, tác giả, ngày
đăng và URL. Bản quyền bài gốc thuộc về tờ báo.
