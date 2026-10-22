# Trạng thái triển khai ngày 22 tháng 10 năm 2026

Đã chuyển từ bộ thiết kế sang ứng dụng chạy được. SRS/DECISIONS/TEST_PLAN là cơ
sở thiết kế; bảng kết quả thực nằm trong VALIDATION và evidence, không suy ra
“đã pass” từ một mục còn được ghi dưới dạng kế hoạch.

## Những khác biệt được ghi nhận

- Dùng MySQL 8.0.46/InnoDB trên máy sẵn có để kiểm thử; đề xuất ban đầu là 8.4.
  DDL tương thích các tính năng InnoDB/JSON/CHECK của bản thử. Chưa tự khai đã
  chạy một lượt nghiệm thu riêng trên 8.4.
- SQLAlchemy Core phản chiếu schema thay vì 38 lớp ORM; mỗi request/task vẫn có
  session/giao dịch riêng. Alembic dùng schema.sql cho migration 0001.
- Revision 0002 lưu snapshot tên/đơn vị báo giá. Báo giá đã chấp thuận và còn
  hạn giữ cả giá và phí giao đã chốt; chỉ chuyển đơn với khu/cách giao phù hợp,
  không âm thầm lấy phí mới sau khi chính sách thay đổi.
- API config được cụ thể hóa dưới `/admin/config/{kind}`, không phải wildcard
  CRUD tùy ý. OpenAPI tại `/docs` backend mô tả các route thực; PROTOCOL bổ sung
  JSON body và bảng ánh xạ.
- Stream catalog mang các offer đã thay đổi với **giá của đúng nhóm** và IDs đã
  bỏ khỏi danh mục; trình duyệt áp dụng trực tiếp. Thay đổi cấu hình diện rộng
  dùng refresh. Đơn/chat/thông báo giữ topic user/admin theo quyền.
- Proxy TLS thử bằng Node.js, một FastAPI worker. Không có Redis/shared bus.
- Báo cáo ngày/tháng hiện tổng hợp theo UTC, giao diện ghi rõ UTC; chưa có bộ
  chọn múi giờ/báo cáo kế toán. COD chỉ ghi doanh thu khi DELIVERED.
- UI giữ hàng/giá/phí đang soạn, yêu cầu xác nhận lại khi version thay đổi.
  Không có chỉnh sửa ngoại tuyến; yêu cầu đã gửi nhưng mất ACK có mã để gửi lại.
- Snapshot working set có tối đa 50 đơn/thông báo; API đơn/users có phân trang,
  lịch sử chat có cursor. Giao diện không tải toàn bộ dữ liệu của 2.000 người.
- Retention tự động event/outbox chưa bật; dữ liệu được giữ để đối chiếu thực nghiệm.
- Thử tải đã thực hiện chỉ được công bố theo đúng mode, số kết nối, tốc độ đọc
  và thời gian trong file kết quả; không đồng nhất với 2.000 người đặt đơn/s.

## Phần phụ thuộc bên ngoài

SMS/email thật cần tài khoản dịch vụ; demo không phát sinh tin nhắn hoặc chi
phí ngoài. Nghiệm thu trên hai máy LAN, phản hồi người mua thực tế, tên miền,
Compilatio và xác nhận đóng góp của từng sinh viên cần nhóm thực hiện.
Không có khảo sát, chứng nhận hay kết quả nhà cung cấp nào được tự tạo.
