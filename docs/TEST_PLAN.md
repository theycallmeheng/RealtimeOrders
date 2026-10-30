# Kế hoạch kiểm thử và thực nghiệm

**Đây là kế hoạch thiết kế. Kết quả đã chạy nằm ở VALIDATION.md và evidence/.**
Không coi mọi biến thể trong TC01–TC28 hoặc toàn bộ ma trận E1–E3 là đã thực thi
chỉ vì có test liên quan. Các lượt đo thực có cấu hình và thời lượng riêng.
Không dùng ảnh/log/số liệu của project khác. Các ngưỡng dưới đây là mục tiêu
đề xuất, không phải kết quả hoặc cam kết đã đạt.

## 1. Các lớp kiểm thử

- Unit: Decimal, quantity step, trạng thái, chính sách giao, lọc từ và DTO.
- Integration: MySQL/InnoDB riêng, transaction và nhiều kết nối DB thật;
  HTTP/WSS thật ở backend. SQLite không chứng minh được lock của InnoDB.
- Browser: trình duyệt thật qua HTTPS/WSS và reverse proxy, máy tính/điện thoại.
- Load: phiên/token hợp lệ với user khác nhau; không gọi SMS tốn phí trong load
  test. OTP test provider riêng và có nhãn; thử SMS thật bằng số được phép.

## 2. Ca chấp nhận

| ID | Kịch bản | Kết quả bắt buộc |
|---|---|---|
| TC01 | OTP Zalo thành công/từ chối; chọn SMS ngay hoặc sau 60 giây; SMS lỗi; mã cũ, hết hạn, dùng lại và giới hạn gửi | Không tạo user hoạt động khi OTP không hợp lệ; chỉ mã mới còn hiệu lực; không log OTP/token hoặc báo gửi thành công khi provider lỗi |
| TC02 | Hai đăng ký cùng SĐT/email; email chưa xác minh | Chỉ một định danh hợp lệ; chưa xác minh không đăng nhập bằng email |
| TC03 | Login/logout/idle/absolute TTL/khóa/xóa mềm khi đang WSS | Phiên và socket hết quyền; heartbeat không giữ phiên mãi |
| TC04 | Hai request đồng thời thêm địa chỉ thứ ba/tư và chọn default người khác | ≤3, default thuộc đúng user; đơn cũ không đổi khi sửa địa chỉ |
| TC05 | Giá nhóm khác, giả group/price từ client | Giá/phí do server quyết định; không lộ nhóm khác qua HTTP/WSS/replay |
| TC06 | Kg 0,100/0,300, hộp số lẻ, số âm/NaN/chuỗi lỗi và ROUND_HALF_UP | Decimal đúng bước; lỗi có code; tổng bằng các dòng + phí |
| TC07 | Giao tập trung sinh viên/giao riêng đủ hoặc thiếu điều kiện | Miễn phí tập trung; kiểm tra khu/mức tối thiểu/phí riêng đúng |
| TC08 | Mở/đóng bán, sửa giá/đơn vị và tạo đơn ở ranh giới | Dừng nhận đơn khi đóng; snapshot cũ còn; giá đổi cần xác nhận lại |
| TC09 | Tạo nhiều PENDING và retry sau mất HTTP response | Không trừ kho, một clientOrderId chỉ có một đơn, pending stats đúng |
| TC10 | Hai admin cùng duyệt 7 kg và 6 kg khi có 10 kg | Không âm kho; nhiều nhất một đơn duyệt; ledger/response đúng |
| TC11 | Duyệt cùng đơn nhiều key; đơn nhiều dòng có một dòng thiếu | Chỉ một lần trừ; all-or-nothing, không đổi các dòng còn lại khi thất bại |
| TC12 | Chuyển trạng thái sai/version cũ/cancel PENDING | Bị từ chối đúng; history không mất; PENDING hủy không hoàn lượng chưa trừ |
| TC13 | Xin hủy, chấp thuận/retry/từ chối; hủy cạnh tranh SHIPPING | Chỉ hoàn khi chấp thuận trước giao; đúng một lần; không vừa giao vừa hoàn |
| TC14 | Yêu cầu hàng → báo giá mới/hết hạn → khách đồng ý → chuyển hai lần | Chỉ giá/phiên bản còn hiệu lực; một đơn liên kết; số lượng/giá đúng thỏa thuận |
| TC15 | Chat/ảnh, hai hội thoại, forged conversation/asset; retry ACK mất | Không lộ/chèn ảnh người khác; chỉ một message canonical |
| TC16 | Từ cấm viết hoa/Unicode/ranh giới từ; notes và tên | Nội dung official được che, cảnh báo/log/admin; không lọc mật khẩu/OTP |
| TC17 | Offline lúc hàng mới/chat/đơn đổi, read/unread và subscribe | Lưu thông báo; đọc lại được; không nhân đôi vì replay/fan-out retry |
| TC18 | Báo cáo tại biên ngày/tháng UTC+7; các trạng thái đơn | Doanh thu/phí riêng từ DELIVERED, số đơn từng trạng thái chính xác |
| TC19 | Sai Origin/CSRF/session, giả topic, frame/JSON lỗi, flood, SQL injection/XSS payload | Bị chặn hoặc escape đúng; không crash/bypass auth; không lộ dữ liệu private |
| TC20 | Vào giữa cập nhật, reconnect thiếu ≤500 hoặc quá cap, reload không model | Replay hoặc snapshot đúng; không mất khoảng giữa snapshot/live |
| TC21 | A bắt đầu trước nhưng B commit trước; và A giữ head lock khi B xin seq cùng topic | Seq theo thứ tự commit/lock thực; B không vượt head chưa commit; cursor không bỏ event |
| TC22 | Giết backend sau commit trước ACK; sau enqueue trước mark outbox | Dữ liệu còn, phát lại/idempotency không tạo đơn/message/notification trùng |
| TC23 | Một người nhận chậm, queue/buffer đầy và tạo tải đồng thời | Chỉ socket đó đóng/resync; RAM có trần, người khác vẫn nhận |
| TC24 | Khóa/đổi nhóm khi có dữ liệu chờ trong socket và replay cũ | Thu hồi phiên và bỏ topic cũ; API không dùng nhóm giá client khai |
| TC25 | Ảnh giả MIME/SVG/quá kích thước/pixel/path traversal | Từ chối/đổi tên an toàn; chat asset không public; raw metadata không lộ |
| TC26 | 360px/laptop, bàn phím, double-click, thiếu kho/đổi phí/mất mạng | Hành động truy cập được; lỗi rõ; không tự xác nhận tiền mới |
| TC27 | Dừng notification job giữa lô, chạy lại, theo dõi nhiều khách | Cursor/lịch sử bền vững, mỗi user/fact/kind một thông báo |
| TC28 | Backup/restore DB và media vào môi trường thử mới | Đọc lại đơn/ảnh/event; thông tin quyền còn, không dùng DB làm việc |

Mỗi module có test của người phụ trách. Các ca concurrency dùng barrier/điểm
ngắt có kiểm soát, kiểm tra cả dữ liệu DB và response/event, không dựa vào sleep
ngẫu nhiên hoặc chỉ nhìn giao diện.

## 3. Thực nghiệm E1 — tính đúng đắn giao dịch

- 2, 20 và 100 request duyệt cạnh tranh, lặp 3 lần trên DB mới; thêm case nhiều
  dòng lock thứ tự đảo, deadlock retry, nhiều key trên một order, cancel-vs-ship.
- So `available = opening + manual_adjust - approved + cancelled_restore`,
  unique movement và status/history; hash/số bản ghi chuẩn hóa theo domain.
- Bằng chứng chính là không vi phạm bất biến. Baseline read-then-write không
  khóa chỉ chạy trên DB test để minh họa lỗi, không đưa vào code triển khai.

## 4. Thực nghiệm E2 — WSS và polling

| Thành phần | Cấu hình so sánh |
|---|---|
| Người dùng | 100 / 500 / 1.000 / 2.000 user, mỗi user 1 session và 1 socket ở WSS |
| Nhóm | 50% sinh viên, 50% người đi làm, cùng danh mục 100 offer |
| Nguồn thay đổi | Một nguồn admin đổi 2 offer/giây, cùng seed/kịch bản |
| Baseline | HTTPS polling mỗi 2 giây, trả cùng trường working set |
| Đề xuất | HTTPS bootstrap + WSS event theo nhóm |
| Thời gian | Warm-up 15 giây, đo 60 giây, lặp 3 lần mỗi cấu hình/mode: 24 lượt |
| Điều khiển | Cùng TLS, dữ liệu, giới hạn, compression và keep-alive; đổi thứ tự mode giữa các lần |

Đo byte server vào/ra, message/API count, truy vấn DB, CPU/RAM, p50/p95 đến
observer áp dụng model và tỷ lệ hội tụ. Không trộn tải ảnh/static assets/OTP
vào phép so truyền thay đổi. Khai báo nếu chỉ có nhiều kết nối rảnh, không gọi
đó là 2.000 người đặt hàng mỗi giây.

## 5. Thực nghiệm E3 — workload nghiệp vụ và phục hồi

- Chạy tăng dần 100→500→1.000→2.000 session. Đề xuất toàn hệ thống 10 đặt đơn/s,
  2 duyệt/s, 5 chat/s và 2 thay đổi danh mục/s, công bố tỷ lệ/mức thực phát được.
- Mỗi mức warm-up 15 giây + đo 60 giây, 3 lần. Tại giây 20 ngắt 10% client
  trong 5 giây trong khi server tiếp tục; đo thời gian từ nối lại đến hội tụ.
- Có cả khách rảnh và khách thao tác; dùng dataset đủ hàng cho số đo độ trễ,
  riêng kịch bản thiếu kho E1. Đếm lỗi thiếu kho/version/rate-limit riêng.
- Dừng tăng tải khi lỗi hệ thống >1%, p95 vượt mục tiêu hoặc tài nguyên bão hòa;
  lưu cả lượt không đạt. Nếu sửa lỗi công cụ thì giữ raw cũ, lý do và lượt đo lại.

Độ trễ đồng bộ: producer và observer dùng chung clock của bộ tạo tải; nếu phân
tán generator, dùng ACK/round-trip hoặc cơ chế đo được mô tả rõ, không lấy UTC
hai máy trừ nhau tùy ý. Thời gian từ server commit có thể đo riêng trong server;
không đánh đồng với thời gian pixel được vẽ trên browser. Báo median hoặc mean
theo run phải ghi rõ; trung bình p95 không phải p95 gộp.

## 6. Mẫu dữ liệu và bằng chứng

Seed giả có nhãn: 2 nhóm, 2 admin, tối đa 2.000 khách, mỗi khách 1–3 địa chỉ,
100 SKU/offer, đơn đủ các trạng thái, hội thoại/ảnh tự tạo. Không dùng dữ liệu
khách thật hoặc số điện thoại thật trong phép tạo tải.

```text
evidence/<run-id>/
  environment.json    # commit, lockfile hash, máy, OS, TLS, worker/pool, mạng
  config.json         # số user/socket, tốc độ yêu cầu, dataset/seed
  raw.csv             # operationId, category, time, latency, status, error
  summary.json        # quantile/counters/tỷ lệ hội tụ, phương pháp tổng hợp
  server-metrics.csv  # CPU/RAM/DB/queue, định nghĩa scope
  screenshots/        # chỉ app và dữ liệu test được phép
```

Demo trên ít nhất 2 thiết bị thật cùng mạng: máy người bán + máy/điện thoại
khách. Ghi rõ loopback nếu chỉ có một máy; 2.000 client mô phỏng không thay thế
kiểm tra responsive và luồng người dùng. Thu phản hồi ngắn về hiểu trạng thái
chờ duyệt, số bước đặt hàng và theo dõi giao; không bịa khảo sát hoặc điểm đánh giá.

## 7. Điều kiện hoàn thành

TC01–TC28 có bằng chứng, unit/integration/browser pass; real SMS được kiểm tra
hoặc ghi rõ bị chặn bởi dịch vụ; app chạy lại từ source/DB mới; test HTTPS/WSS,
đọc riêng tư, concurrent approve/cancel và restore đạt. Tải 2.000 đạt hay chưa
phải có số liệu; bảng kết quả không được tự điền giá trị kỳ vọng. Báo cáo theo
mẫu môn học, Compilatio và xác nhận đóng góp cá nhân là các bước bàn giao riêng.
