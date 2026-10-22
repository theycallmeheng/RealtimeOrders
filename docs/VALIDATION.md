# Kết quả kiểm chứng RealtimeOrders

Ngày 22/10/2026. Tất cả số liệu dưới đây thuộc dự án này, không dùng kết quả BoardLAN/game.

- Python: **50 ca, 0 lỗi**; nguồn `evidence/integration.xml`.
- Browser Edge: **5 đạt, 0 lỗi, 0 bỏ qua**; nguồn `evidence/browser-results.json`.
- Build Next.js/TypeScript chạy thành công. Cookie Secure, HTTPS/WSS tự ký trong môi trường thử.
- Backup/restore vào database mới: `evidence/restore-check.json`; dữ liệu nghiệp vụ và hash bản sao ảnh được đối chiếu.
- Backend dừng → commit event pending → khởi động → publish/replay WSS và order hash giữ nguyên: `evidence/restart-probe.json`.

## Tải kết nối

| Run | Khách / socket cuối | Giây đo | GET/s thực | API p95 ms | Event p95 ms | Lỗi |
|---|---:|---:|---:|---:|---:|---:|
| `100-807b2b98.json` | 100 / 100 | 30 | 9.13 | 68.84 | 346.85 | 0 |
| `500-9b215ef0.json` | 500 / 500 | 30 | 6.83 | 359.13 | 629.74 | 0 |
| `1000-4d1994c3.json` | 1000 / 1000 | 30 | 4.83 | 768.7 | 983.21 | 0 |
| `2000-8b38c1c6.json` | 2000 / 2000 | 60 | 0.32 | 6412.63 | 7523.74 | 0 |
| `2000-fa612b8a.json` | 2000 / 2000 | 60 | 5.75 | 750.71 | 1137.86 | 0 |

Tất cả các lượt yêu cầu 10 GET/s toàn hệ thống; không phải 10 GET/s mỗi khách. Generator, proxy, FastAPI và MySQL cùng máy Windows/loopback. Workload đặt/duyệt đơn là **0/s**, do đó không coi đây là chứng minh 2.000 người đang mua hàng tích cực.

Lượt theo lô `2000-fa612b8a.json` có 200 socket phục hồi sau khi ngắt 10% tại giây 20 và chờ 5 giây. p95 nối lại đến SYNC_END 20294.1 ms, gồm chờ semaphore của generator, không gồm 5 giây cố ý ngắt. Dùng snapshot, không phải replay incremental.

**Giới hạn:** Giữ được 2.000 kết nối, nhưng chưa đạt đồng thời tốc độ đọc yêu cầu và mục tiêu p95 event 500 ms ở mức tải đó. Không xóa các lượt chưa đạt. Các lượt đầu khác phiên bản/working set (100/500 có các đợt TEST còn mở; sau đó đã đóng), không dùng bảng này như thí nghiệm nhân quả có kiểm soát cho mọi tối ưu. Lượt cuối còn có thêm reconnect. Raw resource samples của lượt đầu có wrapper process; không cộng mọi dòng rồi gọi là RAM/CPU server.

## WSS so với polling

Nguồn `997ec04f.json` và CSV observations cùng tên. 100 khách khác nhau, hai nhóm giá, 100 offer thử, 2 thay đổi/s. Warmup 5s, đo 30s, 3 lần/mode, đảo thứ tự mode giữa các lần.

| Mode | Lần | GET | MiB JSON | Quan sát mới | p50 ms | p95 ms | Hội tụ sau drain 2,5s | Lỗi |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| wss | 1 | 0 | 5.46 | 5900 | 164.16 | 238.11 | 100/100 | 0 |
| polling | 1 | 752 | 55.49 | 5254 | 3748.65 | 6776.49 | 23/100 | 0 |
| polling | 2 | 777 | 57.33 | 5274 | 3592.93 | 6176.44 | 25/100 | 0 |
| wss | 2 | 0 | 5.55 | 6000 | 179.93 | 271.89 | 100/100 | 0 |
| wss | 3 | 0 | 5.46 | 5900 | 172.54 | 282.13 | 100/100 | 0 |
| polling | 3 | 1330 | 98.14 | 1725 | 2485.8 | 5753.34 | 98/100 | 0 |

Payload JSON trung bình WSS thấp hơn 92.2% trong workload này. Không gồm header/TLS/packet capture/bootstrap. Không tự suy ra tiết kiệm đường truyền ở mọi workload. Observer ghi latency từ trước transaction producer đến khi parse phiên bản mới bằng cùng perf_counter; loại phiên bản sinh trong warmup. Không phải thời gian pixel xuất hiện trên browser.

Polling có thể trễ và chưa hội tụ trong 2,5s drain do hàng đợi; không diễn giải thành mất gói TCP hay dữ liệu vĩnh viễn sai. Các lượt thăm dò `validTiming=false` bị loại khỏi so sánh latency cuối vì công cụ cũ tính cả version từ warmup; raw vẫn được giữ và có exclusionReason.

## Phạm vi các kiểm tra

Các ca Python bao phủ các phần chính TC01–TC28: OTP sai/hết hạn/reuse; quyền/CSRF/Origin; email demo; địa chỉ đồng thời; giá nhóm; Decimal/số lỗi; giao tập trung/mức tối thiểu; pending/dedup; tranh kho; duyệt nguyên đơn; hủy/hoàn; version; báo cáo; chat/ảnh/kiểm duyệt; quote hết hạn và snapshot giá/phí/tên; WSS snapshot/replay/frame; idle monitor; queue giới hạn; notification job và thứ tự head lock.

Đây **không phải** tuyên bố mọi biến thể trong từng TC hoặc ma trận E1–E3 đều đã chạy. Chưa có ma trận 24 lượt 60s ở mọi mức tải, fault injection ở mọi điểm commit, thử chậm bằng mạng nhiều máy, đo trên hai thiết bị LAN, thử người dùng, SMS/email nhà cung cấp và kiểm tra Compilatio.

Các phép tải chính được chạy trước một số chỉnh sửa cuối về snapshot thông tin theo dõi và báo giá; luồng nghiệp vụ/giao thức cuối được kiểm tra lại bằng Python/browser. Không coi số liệu này là SLA của mọi bản build hoặc môi trường triển khai.

## Trước khi nộp

Nhóm xác nhận đóng góp cá nhân, hiểu code, thử hai thiết bị, điền dữ liệu bán hàng thực tế, kiểm tra Compilatio và tự nộp theo hướng dẫn. Adapter có mã chưa đồng nghĩa đã gửi SMS/email thật.
