# Kế hoạch triển khai nhóm 17

Ngày lập 22/10/2026. Hạn môn học hiện có: 23:59 ngày 31/10/2026, trừ khi thầy
điều chỉnh cho đề tài mới. Đây là lịch đề xuất, không khai báo công việc đã làm.

## 1. Tổ chức và thứ tự ưu tiên

Một repository, `frontend/`, `backend/`, `infrastructure/`, `tests/`, `docs/`.
Một backend nghiệp vụ; hai khu UI; hợp đồng HTTP/WSS chung. Tích hợp mỗi ngày,
nhánh nhỏ, review chéo. Mỗi thành viên viết test/tài liệu phần mình và giải thích
được toàn luồng đặt–duyệt–đồng bộ. Không giao toàn bộ kiểm thử cho một người.

Ưu tiên theo **thứ tự hoàn thành**, không phải tự ý bỏ phần ở cuối:

1. Chạy xuyên suốt browser → API → MySQL → WSS từ ngày đầu.
2. Đăng ký/xác thực, địa chỉ, hàng/giá/giao và đơn có transaction.
3. Trạng thái/hủy, reconnect/outbox, thông báo, chat/ảnh và kiểm duyệt.
4. Yêu cầu hàng/báo giá, báo cáo, kiểm thử tải, restore và tài liệu.

Nếu thiếu thời gian phải báo đúng chức năng còn thiếu và thảo luận lại phạm vi;
không đánh dấu tất cả FR đã làm vì có màn hình mock.

## 2. Phân công đề xuất

| Thành viên | Phần chính | Test/tài liệu chịu trách nhiệm | Review chéo |
|---|---|---|---|
| Nguyễn Đức Hưng — B23DCCN368 | FastAPI nền tảng; OTP/session/role; tài khoản/địa chỉ; moderation service dùng chung | TC01–04,16,19,24; auth/định danh và cấu hình bí mật | Hào review socket/session; Thiệp review account locks |
| Đỗ Quang Thiệp — B23DCCN787 | Đặt/duyệt/hủy; ledger, idempotency, state machine; chuyển yêu cầu thành đơn | TC06,09–14,21–22; transaction và consistency | Quân review schema/giá; Hưng review quyền |
| Vũ Đức Mạnh — B23DCCN535 | Next.js khu khách; auth UI, shop/checkout, đơn/yêu cầu, hook WSS và responsive | TC05,07–08,20,26; trạng thái mạng và trải nghiệm | Hào review reducer/cursor; Quân review component |
| Lê Nguyễn Hồng Quân — B23DCCN675 | Khu admin; catalog/pricing/delivery API; phối hợp migration/seed; báo cáo | TC05,07–08,18,28; schema, chính sách và truy vấn | Thiệp review lock/ledger; Mạnh review UX |
| Trịnh Văn Hào — B23DCCN284 | WSS hub, stream/outbox/fan-out; chat/ảnh/thông báo; cấu hình TLS và bộ đo | TC15,17,19–25,27; giao thức/metrics/load | Hưng review auth/media; Thiệp review durable events |

Thiệp và Quân thống nhất schema trước thêm migration; Hào cung cấp hàm append
event trong cùng transaction để các module khác gọi, không copy logic outbox.
Mạnh và Quân dùng chung types/components; Hưng cung cấp dependency xác thực
chung cho API/WSS. Các ID test trùng là phối hợp, không phải hai bản test rời.

## 3. Lịch 22–31/10/2026

| Ngày | Kết quả tích hợp cuối ngày | Điểm kiểm tra |
|---|---|---|
| 22 | Chốt đặc tả; scaffold; MySQL dev riêng; migration đầu; hai UI mở cùng origin; HELLO WSS | Một thay đổi mẫu lưu DB rồi xuất hiện ở browser khác; xác định người phụ trách SMS/hạ tầng |
| 23 | Đăng ký OTP adapter, login/session, role, địa chỉ; seed 2 nhóm/2 admin | Phone unique, max3 địa chỉ, cookie/Origin; ghi rõ real/fake SMS |
| 24 | Catalog theo ngày, giá nhóm, giao tập trung/riêng, UI shop/admin | Hai khách thấy đúng giá; admin đổi hàng có event; checkout kiểm tra phí |
| 25 | Tạo đơn snapshot và duyệt transaction; admin/khách tích hợp | TC09–11, không âm kho, retry không tạo/trừ trùng |
| 26 | Chuẩn bị/giao/hoàn tất; yêu cầu hủy và hoàn kho; lịch sử | TC12–13, cancel-vs-ship, đơn cũ không đổi giá/địa chỉ |
| 27 | Stream/replay/snapshot/outbox hoàn chỉnh; thông báo và fan-out; TLS | TC17,20–24,27, thử restart và một receiver chậm |
| 28 | Chat ảnh, kiểm duyệt, yêu cầu hàng/báo giá/chuyển đơn, báo cáo cơ bản | TC14–16,18,25; đầy đủ các luồng FR01–20 ở mức hoạt động |
| 29 | Regression và browser trên 2 thiết bị, 360px; sửa lỗi; seed/load harness | TC01–28, test contract; chạy tải nhỏ trước, thử backup/restore |
| 30 | Thực nghiệm E1/E2/E3 tăng tới mục tiêu, phân tích dữ liệu, hoàn thiện báo cáo | Raw/config/commit được giữ; không giấu lượt lỗi hoặc bịa mức 2.000 |
| 31 | Sửa lỗi theo bằng chứng, đóng bản bàn giao, chạy từ source sạch, diễn tập | Đủ Source/Report, Compilatio theo yêu cầu môn, xác nhận đóng góp thực |

Lịch này dày với toàn bộ phạm vi. Nếu nền tảng/SMS/MySQL chưa sẵn sàng ngày 22,
cần điều chỉnh kế hoạch ngay; không dồn tất cả tích hợp vào ngày 29. Kế hoạch
không cam kết đã có dịch vụ sản xuất 2.000 người trong 10 ngày.

## 4. Mốc và Definition of Done

- M1: auth + hàng + WSS qua TLS; giá nhóm và quyền có test.
- M2: đặt/duyệt/hủy nhất quán, retry/restart không làm sai kho.
- M3: đủ các module nghiệp vụ và UI; chat ảnh và yêu cầu hàng dùng dữ liệu thật.
- M4: browser, concurrency và thử tải có bằng chứng; bản bàn giao chạy lại được.

Mỗi task xong khi code nối qua tầng thật, có error handling và test tương ứng,
OpenAPI/DTO khớp, không log bí mật, reviewer chạy được. Một screen với dữ liệu
cứng không được tính là xong module. Đo hiệu năng chỉ bắt đầu trên commit cố định;
sửa code ảnh hưởng phép đo thì ghi lý do và chạy lại cấu hình bị ảnh hưởng.

## 5. Backlog cụ thể

| Epic | Task đầu ra | Phụ thuộc |
|---|---|---|
| EP01 Nền tảng | Monorepo, config env, DB/migration, health/readiness, TLS proxy, CI cơ bản | Hạ tầng dev |
| EP02 Auth | OTP/provider, register/login/reset, session/revoke, email tùy chọn, max3 address | EP01 |
| EP03 Catalog | SKU/ảnh/đơn vị/đợt, giá nhóm, delivery policy, API/DTO | EP01 + auth |
| EP04 Order | Checkout, snapshots, idempotency, approve/ledger/state/cancel | EP02–03 |
| EP05 Realtime | Topic ACL, durable append, outbox, handshake/sync, queue bounded | EP01; tích hợp dần với EP02–04 |
| EP06 Giao tiếp | Chat/ảnh, moderation, notification/subscription/jobs | EP02 + EP05 |
| EP07 Yêu cầu hàng | Request/quote/version/expiry/accept/convert vào EP04 | EP03–04 |
| EP08 Admin/reports | Screens xử lý và truy vấn ngày/tháng, audit | EP02–07 |
| EP09 Chứng minh | TC01–28, load/polling baseline, restore, data/log, báo cáo | Tích hợp liên tục; khóa commit trước đo |

## 6. Gói nộp dự kiến

Tên báo cáo theo hướng dẫn: `Nhom17_RealtimeOrders_Report.docx`; thư mục source
`Nhom17_RealtimeOrders_Source`. Tên đổi nếu nhóm chọn tên project khác.

```text
Nhom17_RealtimeOrders/
  Source/       # code, migration, seed, config mẫu, README, tests và bằng chứng
  Report/       # bản báo cáo cuối đã được nhóm kiểm tra
```

Báo cáo theo technical paper: bài toán/động lực, liên quan, kiến trúc, protocol,
transaction, thực nghiệm, kết quả, discussion, contributions, giới hạn, hướng
phát triển và tham khảo. Chuẩn bị Compilatio theo Instruction.md, lưu kết quả
thực. Chỉ khai báo đóng góp cá nhân có minh chứng; bảng phân công trên chưa phải
khai báo hoàn thành.
