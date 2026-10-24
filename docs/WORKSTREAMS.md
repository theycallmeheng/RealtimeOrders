# Năm phần công việc RealtimeOrders

Giữ nguyên cách chia đã chốt với người dùng; chưa gán tên thành viên.

| Phần | Phạm vi |
|---|---|
| 1. Nền tảng và tài khoản | Thiết kế CSDL, migration, đăng ký/đăng nhập, OTP, hồ sơ và phân quyền |
| 2. Backend bán hàng | Danh mục, giá nhóm, tồn kho, đặt/duyệt/giao/hủy/hoàn kho, yêu cầu và báo giá |
| 3. Backend realtime | WebSocket, chat, thông báo, outbox, đồng bộ sự kiện và reconnect |
| 4. Giao diện khách hàng | Xem hàng, giỏ hàng, đặt/theo dõi đơn, yêu cầu hàng, chat và thông báo |
| 5. Giao diện người bán/quản trị | Quản lý hàng/kho, xử lý đơn, tài khoản, báo cáo và kiểm duyệt |

Kiểm thử, tài liệu, tích hợp, proxy và vận hành đi kèm từng phần, không tạo thành phần
thứ sáu hoặc chuyển toàn bộ trách nhiệm sang một thành viên.

Đợt tối ưu 24–25/10/2026 chỉ sửa cách thực hiện bên trong phần 1–3: truy vấn xác
thực, tải giá/đơn theo lô, ghi/phát sự kiện, đồng bộ và TCP loopback. Không chuyển tính năng
giữa các phần, không đổi API v1, schema nghiệp vụ hay luồng giao diện. Hai phần
frontend giữ các màn hình và trách nhiệm như trước. Xem
[kết quả tối ưu](PERFORMANCE_2026-10-24.md).

Ngày 25/10 tiếp tục tối ưu vòng lặp mạng và outbox trong phạm vi trên, không
đổi cơ cấu hoặc phân công. Xem [đo lại độ trễ](LATENCY_2026-10-25.md).
