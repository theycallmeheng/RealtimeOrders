# Hệ thống thiết kế RealtimeOrders

RealtimeOrders là cửa hàng thực phẩm và nơi xử lý các đơn trong ngày. Giao diện mua hàng ưu tiên ảnh, giá và thao tác trên điện thoại. Khu vực điều hành ưu tiên các việc cần xử lý, bảng dữ liệu và trạng thái có nhãn rõ ràng.

## Nguồn thiết kế

Dùng [UI/UX Pro Max v2.15.0](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/releases/tag/v2.15.0) với ba truy vấn:

```powershell
python .agents/skills/ui-ux-pro-max/scripts/search.py 'grocery online store mobile checkout' --design-system -p RealtimeOrders -f markdown
python .agents/skills/ui-ux-pro-max/scripts/search.py 'order management inventory dashboard' --design-system -p RealtimeOrders -f markdown
python .agents/skills/ui-ux-pro-max/scripts/search.py 'responsive navigation image layout' --stack nextjs
```

Cả hai hệ gợi ý chọn bố cục phẳng, tương phản rõ và hiệu ứng ngắn. RealtimeOrders áp dụng các quy tắc này cho giao diện đang có, giữ bảng màu xanh chàm đã chốt và dùng ảnh hàng hóa hiện có. Ảnh cần một khung có kích thước dự kiến để giảm nhảy bố cục.

## Màu và chữ

| Vai trò | Biến CSS | Giá trị |
| --- | --- | --- |
| Hành động chính | `--accent` | `#2447A6` |
| Nền trang | `--page` | `#F6F8FC` |
| Nền biểu mẫu, thẻ | `--surface` | `#FFFFFF` |
| Mục, dòng đang chọn | `--accent-soft` | `#E5ECFF` |
| Giá ưu đãi | `--offer-ink` | `#A94717` |
| Chữ chính | `--ink` | `#16223A` |
| Chữ phụ | `--muted` | `#4C5B76` |
| Thanh bên điều hành | `--rail` | `#1B2A54` |

Các màu thành công, cảnh báo và lỗi đi kèm nhãn trạng thái. Dùng font hệ thống có tiếng Việt, ưu tiên Segoe UI trên Windows. Dùng cỡ số cố định theo chiều ngang cho tiền và số liệu. Khoảng cách theo bội số 4 px, bo góc 6 px cho điều khiển, 10 px cho khối nội dung và 14 px cho hộp thoại.

## Bố cục và tương tác

- **Cửa hàng:** hiển thị tên, giá, ưu đãi và lượng còn theo thứ tự nhất quán. Giỏ và phần thanh toán nhóm thông tin nhận hàng, phí, tổng tiền và xác nhận đặt đơn. Thanh mua sắm trên điện thoại giữ các đích chính sẵn có. Chi tiết phụ vẫn mở được bằng bàn phím.
- **Điều hành:** thanh bên tối với mục đang chọn nổi bật. Bộ lọc nằm trước danh sách, chi tiết đơn lấy đúng dữ liệu từ dòng đã chọn. Bảng rộng cuộn trong vùng bảng. Trên màn nhỏ, danh sách đơn ưu tiên hiển thị kiểu thẻ theo quy tắc sẵn có.
- **Giao hàng và đăng nhập:** tiêu đề, trạng thái, thông tin cần cho việc kế tiếp và nút chính dễ nhìn. Đơn giao tách thao tác xác nhận khỏi thông tin giá và chia chiều rộng cho các nút trên điện thoại.
- **Điều khiển:** vùng bấm 44 px cho các hành động chính trên điện thoại. Giữ viền focus có độ tương phản rõ và trạng thái chữ cho tải, lỗi, giao hàng và thanh toán. Hiệu ứng ngắn và tuân theo chế độ giảm chuyển động.

Khi cập nhật giao diện, dùng các biến trong [indigo-theme.css](../../frontend/app/indigo-theme.css). Kiểm tra chữ và điều khiển ở 360, 390, 768 và 1440 px, đi qua các màn bằng bàn phím, rồi xác nhận các URL, quyền theo vai trò và luồng nghiệp vụ hiện có.
