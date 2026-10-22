# Màn hình và trải nghiệm chính

Theo [DESIGN.md](../DESIGN.md). Các đường dẫn là đề xuất route frontend;
quyền cuối cùng luôn kiểm tra ở backend, không chỉ ẩn menu.

## 1. Khu khách hàng

| Route | Nội dung và hành vi |
|---|---|
| /register | SĐT, xin OTP, nhập mã, đặt mật khẩu/tên; đếm chờ gửi lại, báo giới hạn |
| /login | SĐT hoặc email đã xác minh, mật khẩu; thông báo lỗi không chứa chi tiết kỹ thuật |
| /forgot-password | Xác minh SĐT rồi đổi mật khẩu; không tiết lộ có tài khoản hay không |
| /onboarding | Thêm địa chỉ, chọn mặc định; nêu rõ điều kiện để đặt hàng |
| /shop | Hàng đang mở theo ngày, giá nhóm mình, đơn vị, còn kho và nhu cầu chờ |
| /checkout | Các dòng, số lượng, hình thức giao, phí/tổng, địa chỉ/điểm giao; xác nhận gửi |
| /orders | Đang xử lý/lịch sử, lọc, trạng thái và mã đơn |
| /orders/[id] | Snapshot dòng/giá/giao, timeline, hủy/xin hủy theo quyền; lý do từ chối |
| /requests | Yêu cầu hàng, trạng thái, báo giá; chấp thuận/đặt từ báo giá |
| /messages | Hội thoại riêng, gửi text/ảnh, preview upload và lịch sử phân trang |
| /notifications | Danh sách đọc/chưa đọc, link đúng tài nguyên của mình |
| /account | Thông tin, email tùy chọn, địa chỉ ≤3, theo dõi mặt hàng, đăng xuất |

Màn shop không hiển thị giá nhóm khác. Giá thấp hơn do nhóm không được diễn
giải thành khuyến mãi cho mọi người. Đơn gửi thành công hiện “Chờ duyệt, chưa
giữ hàng”; không dùng “Đã mua thành công” trước khi admin duyệt.

Ở 360px: tìm/lọc gọn, mỗi dòng có tên/đơn vị/giá/còn/số lượng; giỏ và tổng tiền
dễ thấy. Các nút trạng thái không kéo bảng rộng làm ẩn hành động chính.

## 2. Khu quản trị

| Route | Nội dung và hành vi |
|---|---|
| /admin/orders | Bảng hàng đợi, tuổi đơn, tổng, nhóm, cách giao, trạng thái và hành động |
| /admin/orders/[id] | Từng dòng cần/còn, snapshot tiền, địa chỉ, lịch sử; duyệt/từ chối/chuyển giao |
| /admin/cancellations | Yêu cầu OPEN, lý do, điều kiện hoàn, chấp thuận/từ chối |
| /admin/catalog | SKU/danh mục/đơn vị/ảnh; tìm, trạng thái hoạt động |
| /admin/offers | Hàng theo ngày/đợt, lượng còn, giá từng nhóm, mở/đóng và điều chỉnh có lý do |
| /admin/delivery | Khu, điểm/khung giờ, phí và mức đơn tối thiểu theo nhóm |
| /admin/users | Tên, nhóm, trạng thái; khóa/mở/xóa mềm có xác nhận và lý do |
| /admin/requests | Tiếp nhận, báo giá có hạn/phiên bản, theo dõi đơn chuyển đổi |
| /admin/messages | Danh sách hộp chat khách và hội thoại được chọn |
| /admin/moderation | Từ cấm, vi phạm, cảnh báo và hành động tài khoản |
| /admin/reports | Ngày/tháng, số đơn từng trạng thái, hàng giao và doanh thu/phí |
| /admin/settings | Tham số phiên/rate-limit, lịch sử thay đổi; không hiện bí mật provider |

Trang đầu quản trị là công việc cần xử lý, có thể kèm vài số tổng nhỏ; không tạo
dashboard nhiều thẻ trang trí thay cho bảng đơn. Khi người khác đã xử lý đơn,
hiện VERSION_CONFLICT rồi tải lại; không lặng lẽ ghi đè.

## 3. Luồng bắt buộc kiểm tra

1. Đăng ký SĐT → OTP → mật khẩu → địa chỉ → shop → checkout → PENDING.
2. Admin duyệt → khách thấy APPROVED/còn kho mới → PREPARING → SHIPPING → DELIVERED.
3. Sinh viên chọn giao riêng → kiểm tra khu/mức tối thiểu → xem phí → xác nhận.
4. Xin hủy sau duyệt → hiển thị “đang chờ quyết định” → admin chấp thuận →
   CANCELLED và hoàn kho; không hiện hoàn khi mới gửi yêu cầu.
5. Giá/phí đổi trong lúc checkout → hiển thị cũ/mới, yêu cầu xác nhận lại;
   không mất nội dung giỏ và không tự gửi lại với giá mới.
6. Mất mạng sau bấm gửi đơn/chat → giữ ID của thao tác đã gửi, hiện chưa rõ kết
   quả; reconnect/tra cứu kết quả rồi retry; không tạo ID mới mỗi lần bấm.
7. Khóa tài khoản lúc đang chat → đóng phiên, bỏ nội dung private khỏi view,
   quay đăng nhập. Không chỉ tắt nút ở frontend.

Không xếp đơn đã hủy vào doanh thu đã giao. Banner mất kết nối và trạng thái
lưu xuất hiện gần dữ liệu; tránh mở modal lặp lại cho từng lần reconnect.
