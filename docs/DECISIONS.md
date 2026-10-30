# Sổ quyết định và giả định

> Cập nhật đã được người dùng chốt ngày 29/10/2026: menu theo ngày nhiều sản phẩm,
> giới hạn nhóm, Goong và lãi gộp. Chức năng yêu cầu hàng/báo giá (FR12) ngừng hỗ trợ;
> P13 về chưa dùng bản đồ được thay thế. Xem DAILY_SALES.md để biết hợp đồng hiện hành.


Ngày 22/10/2026. Thứ tự ưu tiên: chỉ dẫn trực tiếp mới của người dùng > yêu cầu
người dùng đã chốt > bản mô tả cuối trong link > đề xuất thiết kế của nhóm.
Các câu hỏi/gợi ý trong các câu trả lời cũ của đoạn chat tham khảo không tự trở
thành yêu cầu. Tài liệu này không phải xác nhận của giảng viên/khách hàng.

## Đã xác định

| ID | Quyết định | Cơ sở |
|---|---|---|
| D01 | Web responsive; Next.js, Tailwind, Font Awesome; backend Python, MySQL, WSS | Bản mô tả cuối của đề tài |
| D02 | Hai vai trò chính: khách hàng và quản trị/người bán; ít nhất hai nhóm giá | Bản mô tả đề tài |
| D03 | Chỉ trừ tồn khi duyệt; phải kiểm tra lại và xử lý concurrency | Lựa chọn cuối trong link |
| D04 | Đăng ký SĐT qua OTP Zalo trước; người dùng có thể chọn SMS dự phòng khi Zalo từ chối hoặc sau 60 giây; OTP khôi phục mật khẩu vẫn theo cấu hình SMS; email tùy chọn | Người dùng cập nhật lựa chọn 30/10 |
| D05 | Đơn đã duyệt, chưa bàn giao vận chuyển: khách yêu cầu hủy; admin xác nhận và hoàn kho | Người dùng xác nhận 22/10 |
| D06 | Sinh viên giao riêng theo khu vực, mức đơn tối thiểu và phí admin cấu hình | Người dùng xác nhận 22/10 |
| D07 | Thông báo trong website, lưu để đọc lại; chat riêng có ảnh và lịch sử | Bản mô tả cuối |
| D08 | Che từ, cảnh báo, nhật ký và thông báo admin; báo cáo ngày/tháng | Bản mô tả cuối |
| D09 | Tối đa 3 địa chỉ, có mặc định; email/SĐT duy nhất; xóa mềm và ghi lịch sử khóa/mở | Bản mô tả đề tài |
| D10 | Mục tiêu 1.000–2.000 khách đồng thời, cần đo để xác nhận | Bản mô tả cuối |

## Đề xuất thiết kế để nhóm triển khai

Không phải yêu cầu đã được thầy xác nhận riêng. Nếu được sửa, cập nhật cả SRS,
schema, API và ca kiểm thử liên quan.

| ID | Đề xuất | Lý do và ảnh hưởng |
|---|---|---|
| P01 | Monorepo; một origin; HTTPS API + WSS; Next.js và FastAPI là service riêng | Dễ phân công, cookie cùng origin, một cách chạy |
| P02 | FastAPI, SQLAlchemy async, Alembic; MySQL 8.4/InnoDB | Phù hợp backend Python và transaction; pin version khi bootstrap |
| P03 | Duyệt toàn bộ đơn hoặc không duyệt; không tự cắt bớt sản phẩm | Giữ giá trị đơn đã được khách đồng ý |
| P04 | Đơn PENDING khách tự hủy; APPROVED/PREPARING dùng yêu cầu hủy; SHIPPING/DELIVERED không tự động hoàn kho | Tránh hoàn kho hàng đã giao khỏi người bán |
| P05 | COD; doanh thu hàng và phí giao ghi riêng khi DELIVERED | Chưa có cổng thanh toán hoặc kế toán; không đồng nhất tổng đơn chờ với doanh thu |
| P06 | Tiền VND; đơn vị của một SKU cố định; số lượng Decimal tối đa 3 chữ số thập phân | Có kg và đơn vị nguyên, tránh sai số float |
| P07 | Email muốn dùng để đăng nhập/khôi phục phải được xác minh; chưa xác minh lưu trong challenge, chưa gắn vào users | Tránh chiếm email của người khác; cần kênh gửi email khi bật tính năng này |
| P08 | Tài khoản mới vào nhóm người đi làm; admin chuyển sang nhóm sinh viên | Khách không tự cấp nhóm giá ưu đãi; có thể thay theo quy trình thực tế |
| P09 | Session token ngẫu nhiên lưu hash, cookie HttpOnly/Secure; idle 30 phút, tối đa 24 giờ | Thu hồi được ngay; heartbeat không gia hạn hoạt động người dùng |
| P10 | OTP hết hạn 5 phút, tối đa 5 lần thử, gửi lại sau 60 giây; 5 lần gửi/SĐT/giờ và 20/IP/giờ | Mặc định kỹ thuật cấu hình được, phải kiểm tra với nhà cung cấp |
| P11 | Một worker FastAPI trước; durable event/outbox trong MySQL; thêm bus dùng chung trước khi chạy nhiều worker | Registry socket trong RAM không tự chia sẻ giữa process |
| P12 | Replay tối đa 500 event hoặc 256 KiB; vượt thì snapshot; log event giữ 24 giờ ban đầu | Khống chế phục hồi và giữ RAM có giới hạn |
| P13 | Khu giao theo danh sách admin quản lý; chưa tự geocode hoặc tính khoảng cách bản đồ | Không phát sinh tích hợp bản đồ; địa chỉ thực do người bán kiểm tra |
| P14 | Mở bán OPEN nhận đơn mới; CLOSED dừng nhận mới nhưng vẫn được duyệt các đơn đã đặt hợp lệ nếu chưa khóa xử lý đợt | Tách lịch mở bán và lịch giao/hoàn tất |
| P15 | Phiên đầu không sửa nội dung đơn sau khi gửi; khách hủy/tạo lại hoặc admin từ chối | Giảm trạng thái mơ hồ và giữ snapshot tiền/địa chỉ |
| P16 | Trần một đơn 20 dòng, 5 ảnh mỗi sản phẩm, 3 ảnh mỗi tin nhắn, 5 MiB mỗi ảnh JPEG/PNG/WebP | Giới hạn ban đầu, không dùng làm thành tích đã đo |

## Việc cần thông tin bên ngoài

| ID | Còn thiếu | Phần vẫn làm được |
|---|---|---|
| O01 | OA/ZBS, quyền gửi theo SĐT, access token, template OTP được duyệt; Twilio cho SMS dự phòng/khôi phục, chi phí và số thử hợp lệ | Adapter + fake provider có nhãn demo + kiểm thử; chỉ nghiệm thu tin thật sau khi có cấu hình nhà cung cấp |
| O02 | Hạ tầng/tên miền, TLS, tài nguyên và máy tạo tải | Local compose, TLS thử có chứng thư tin cậy trên máy demo; đo cấu hình thực |
| O03 | Dữ liệu khu giao, điểm giao tập trung, giờ giao, phí và mức tối thiểu | Model/chính sách cấu hình; dữ liệu seed ghi rõ mẫu |
| O04 | Chính sách đổi trả sau SHIPPING/DELIVERED, công nợ và thanh toán khác COD | Không tự hoàn kho sau giao; ghi nhận đây là phạm vi chưa chốt |
| O05 | Tên thương hiệu, quyền sử dụng ảnh/logo hàng hóa | Tên kỹ thuật trung tính và dữ liệu tự tạo |
| O06 | Dịch vụ email khi bật đăng nhập email/khôi phục qua email | Đăng ký và đăng nhập SĐT hoạt động theo D04; email adapter có thể kiểm thử riêng |

Đề xuất giảm chức năng hoặc đổi tiêu chí nghiệm thu phải được ghi lại; không
âm thầm bỏ chat ảnh, yêu cầu hàng, kiểm duyệt hay OTP vì thời gian ngắn.
