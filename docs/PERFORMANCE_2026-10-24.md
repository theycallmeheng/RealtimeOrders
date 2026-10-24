# Tối ưu RealtimeOrders — 24–25/10/2026

Đây là kết quả đợt trước. Kết quả mới với Winloop/outbox ngày 25/10 ở
[LATENCY_2026-10-25.md](LATENCY_2026-10-25.md); giữ nguyên số liệu lịch sử dưới đây.

Yêu cầu: cải thiện các điểm đã đo được, giữ nguyên [năm phần công việc](WORKSTREAMS.md).
Không đổi vai trò, nghiệp vụ, API v1 hay schema; vẫn một worker FastAPI với
MySQL/InnoDB. Mã frontend sản phẩm giữ nguyên.

## Những thay đổi

1. `auth.py` đọc user hiện tại và session bằng cùng truy vấn JOIN. Vẫn kiểm tra
   trạng thái, security version, thu hồi phiên và hạn giờ ở mỗi lần xác thực;
   không cache quyền hoặc kéo dài phiên bằng lượt đọc.
2. `commerce.py` lấy giá nhóm của các đợt trong một truy vấn, gom thống kê/ảnh
   bằng map và chỉ đọc ảnh của những sản phẩm được trả về. Giá nhóm khác chỉ
   được thêm khi đang phục vụ quản trị. Snapshot tải chi tiết tối đa 50 đơn
   bằng bốn truy vấn theo lô, vẫn kiểm tra quyền từng đơn và giữ nội dung như
   API chi tiết đơn.
3. `events.py` ghi event và outbox theo lô trong cùng giao dịch; giữ thứ tự khóa
   topic và seq. Outbox đánh dấu batch đã phát bằng một UPDATE. Publish vẫn chỉ
   đọc các event đã commit; gửi lặp sau sự cố tiếp tục được xử lý bằng seq.
4. Hub lập chỉ mục subscriber theo topic và mã hóa một frame JSON cho tất cả
   người nhận cùng event. Giới hạn 128 message/512 KiB vẫn áp dụng từng client,
   client chậm được tách riêng; unregister xóa chỉ mục topic rỗng.
   Các vòng gửi/nhận dùng task dài hạn thay cho tạo task/timer mỗi thông điệp;
   khóa gửi giữ trọn snapshot và ngăn ACK/event xen vào giữa các chunk.
   Tối đa tám lượt đọc DB phục vụ đồng bộ đồng thời, để dành khả năng xử lý
   nghiệp vụ khi nhiều người nối lại. Xác thực lại sau khi được nhận vào lượt
   đọc; nhả slot trước khi ghi socket để người nhận chậm không giữ slot DB.
5. Proxy nghe cả `127.0.0.1` và `::1`, dùng cùng TLS/router và TCP_NODELAY. Điều
   này tránh chờ chuyển từ IPv6 sang IPv4 khi `localhost` được phân giải ưu tiên
   `::1`. Vẫn chỉ là loopback; không mở thêm listener ra toàn bộ card mạng.
6. Cấu hình chạy LAN tắt `per-message-deflate` của WebSocket. Đây là đánh đổi
   CPU/bộ nhớ với kích thước truyền: JSON không nén có thể tốn thêm băng thông.
   Giữ nguyên TLS, Origin, cookie và giới hạn frame. Không thay thư viện hoặc
   thêm worker; Uvicorn hiện đã tự chọn implementation `websockets-sansio`.

## Phép đo thành phần

`scripts/performance_probe.py` chạy trên bản sao MySQL, thêm 50 đợt tổng hợp;
catalog quản trị đạt cửa sổ tối đa 200 đợt kể cả lịch sử. Mỗi phép đo có 2 warmup
và 10 lần đo; event ghi thử được rollback, fixture catalog đóng sau mỗi lượt.

| Phép đo | SQL trước | SQL sau | p50 trước (ms) | p50 sau (ms) |
|---|---:|---:|---:|---:|
| Xác thực | 2 | 1 | 1,74 | 3,71 |
| Catalog khách | 4 | 4 | 18,72 | 34,37 |
| Catalog quản trị | 204 | 5 | 255,20 | 48,51 |
| Ghi 100 event, ba topic | 209 | 11 | 251,07 | 37,08 |

Giảm số query không có nghĩa mọi latency ở một lượt đo đều giảm: xác thực và
catalog khách có thời gian cao hơn trong lượt sau. Đây là phép đo tuần tự trên
máy Windows dùng chung; không kết luận mọi endpoint nhanh hơn từ bảng này.

Fanout CPU thuần cho 2.000 subscriber, payload text 8 KiB: p50 từ 94,67 ms xuống
4,59 ms; p95 từ 100,55 xuống 9,05 ms. Không gồm WebSocket, TCP/TLS hoặc parse ở
client, nên không đồng nhất với độ trễ đồng bộ đầu cuối.

## Kết nối localhost

Đo riêng trên cùng bản backend tối ưu, thay proxy giữa hai lượt. Trước sửa,
localhost mất khoảng 2.030–2.155 ms để mở WebSocket, trong khi IPv4 trực tiếp
khoảng 17–29 ms. Sau sửa, ba mẫu localhost sau mẫu đầu là 23–25 ms; mẫu đầu
146,61 ms. Bước sync ở backend khoảng 23–42 ms. File đo lưu proxy SHA-256 để
phân biệt phiên bản, không ghi cookie hoặc token.

## Kiểm chứng đầu cuối

Kết quả tổng hợp, đường dẫn dữ liệu thô, mã nguồn được đo và các giới hạn nằm ở
`evidence/performance-20261024/summary.json`. Giữ lại các lượt đo cũ của đợt
[audit](AUDIT_2026-10-24.md); không ghi đè hoặc thay số liệu lịch sử.

Các lượt tải chính dùng cùng kịch bản: 2.000 khách riêng biệt, 60 giây đo sau ramp,
10 GET/s toàn hệ thống, probe 2 giây/lần, ngắt 10% tại giây 20 rồi chờ 5 giây
để nối lại. Mỗi bản dùng DB audit sao chép từ cùng dữ liệu nguồn; không ghi vào
database chính. Generator, proxy, server và MySQL cùng máy; đây là các lượt đo
tuần tự, chưa phải nhiều lần lặp có kiểm soát hoặc cam kết SLA. Catalog đang
bán của từng nhóm được đối chiếu hash giữa DB baseline và DB tối ưu.

Workload tải này không phát sinh đơn mua. Tranh kho, gửi lại, phân quyền,
rollback, version/seq và reconnect được kiểm tra bằng bộ Python/MySQL và Edge
riêng trên một DB audit sạch, không có các fixture PERF của phép đo.

| Lượt 2.000 kết nối | Ramp (s) | GET/s thực | API p95 (ms) | Event p95 (ms) | Phục hồi p95 (ms) | Lỗi |
|---|---:|---:|---:|---:|---:|---:|
| Baseline `5df85c7b` | 154,65 | 6,32 | 655,47 | 730,75 | 20.220 | 0 |
| Tối ưu ban đầu `50895dd5` | 71,44 | 3,73 | 1.316,76 | 2.133,14 | 21.386 | 0 |
| Chẩn đoán IPv4 `0e400269` | 75,90 | 3,85 | 1.015,04 | 1.542,77 | xem raw | 2* |
| Task dài hạn `5a09aebe` | 66,63 | 6,18 | 536,15 | 1.284,45 | 10.280 | 0 |
| Bản cuối `f47c87f6` | 68,34 | 6,90 | 421,71 | 1.007,80 | 9.815,71 | 0 |

Mọi lượt trên giữ đủ 2.000 danh tính hoạt động cuối phép đo và phục hồi 200
client. `*` Hai lỗi `ConnectionClosedOK` ở lượt chẩn đoán do PONG đụng thời
điểm generator chủ động đóng kết nối. Đã sửa generator phân biệt đóng chủ
động; không sửa dữ liệu lỗi trong file cũ. Số liệu byte JSON không đo byte
TCP/TLS sau nén, nên không dùng để kết luận thay đổi băng thông.

Bản cuối giảm thời gian kết nối, phục hồi và p95 API trong lượt này; p50 event
giảm từ 428,93 xuống 380,27 ms nhưng **p95 event tăng từ 730,75 lên 1.007,80 ms**.
Mục tiêu p95 event dưới 500 ms ở 2.000 kết nối và 10 GET/s chưa đạt. Giữ các
thay đổi giảm truy vấn/task và sửa localhost, không công bố mức tải này như
SLA. Kịch bản đầu cuối chỉ chạy một lượt mỗi biến thể, chưa đủ để quy toàn bộ
khác biệt cho từng tối ưu riêng lẻ.

Chẩn đoán CPU được lấy riêng trên 1.000 kết nối trong 20 giây, 1.074 mẫu và
một lỗi lấy mẫu. Phần tự tiêu thụ CPU của `asyncio.windows_events.send` khoảng
14,9%, `_poll` 7,54%, SQLAlchemy `_execute_async` 4,56% và nén WebSocket 4,19%.
Đây là gợi ý về chi phí I/O Windows và nén, không chứng minh một nguyên nhân
duy nhất của p95. Lượt chẩn đoán `1000-89c3ec5e.json` có profiling nên không
gộp với phép đo tải không profiling.

## Kiểm thử hồi quy và phạm vi công việc

Bản cuối được chạy lại bằng toàn bộ 92 ca Python/MySQL, năm ca Edge qua
HTTPS/WSS và phép dừng/khởi động để kiểm tra outbox. Kết quả và trạng thái
39 bảng nguồn được chốt trong `summary.json`; các bộ 81/91 ca trước đó vẫn
giữ nguyên bằng chứng lịch sử. Kiểm thử bổ sung bao gồm rollback batch,
seq, giá riêng theo nhóm, truy vấn chi tiết đơn theo lô và quyền xem đơn,
giới hạn queue, hai họ địa chỉ loopback và sync không bị xen event.

Các thay đổi vẫn thuộc phần nền tảng/tài khoản, backend bán hàng và backend
realtime. Proxy, đo tải và kiểm thử là việc xuyên suốt. Không chuyển chức năng
hoặc người giữa năm phần; mã giao diện sản phẩm và schema không thay đổi.

## Chạy lại

Sau setup, dừng app chính và dùng `scripts/isolated_validation.py prepare` theo
hướng dẫn README. Chạy các công cụ bằng wrapper để giữ đúng DB test:

```powershell
.\.venv\Scripts\python.exe scripts\isolated_validation.py run -- "{python}" scripts\performance_probe.py --label optimized
.\.venv\Scripts\python.exe scripts\isolated_validation.py run -- "{python}" scripts\performance_probe.py --label optimized --connectivity-only
.\.venv\Scripts\python.exe scripts\isolated_validation.py run -- "{python}" scripts\load_test.py --clients 2000 --seconds 60 --rps 10 --reconnect-fraction 0.1 --label performance-recheck
```

`--label` là nhãn file, không tự thay phiên bản backend. Muốn A/B phải dùng đúng
mã trước/sau có SHA trong bằng chứng và hai bản sao nguồn tương ứng. Sau khi
kiểm tra, chạy `finish` để đối chiếu DB nguồn và bật lại app chính. SMS/email
thật và kiểm tra hai máy LAN vẫn là bước nghiệm thu riêng.
