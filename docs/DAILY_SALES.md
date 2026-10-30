# Menu theo ngày, nhóm khách và lãi gộp

Quyết định trực tiếp của người dùng ngày 29/10/2026 thay thế chức năng yêu cầu
hàng/báo giá và giả định chưa dùng bản đồ trong đặc tả 22/10. Năm phần công việc
và cấu hình HTTPS/WSS LAN tiếp tục áp dụng.

## Cách dùng

1. Quản trị vào Sản phẩm: đặt giá nhập/bán mặc định, nhóm được phép mua.
2. Vào Menu theo ngày: chọn ngày bắt đầu, ngày đóng tùy chọn, nhiều món, lượng bán,
   giá nhập và giá từng nhóm; lưu nháp hoặc mở bán. Để trống ngày đóng thì đợt kết thúc
   hết ngày bắt đầu; để trống giờ đóng thì kết thúc hết ngày đã chọn. Có thể tạo
   nhiều menu cùng ngày; các đợt đang mở phải có khung giờ riêng, không chồng lấn.
3. Khách vào Menu hôm nay: thêm món để mở giỏ; mua tiếp hoặc tiếp tục đặt hàng.
4. Khi thanh toán chọn địa chỉ/cách nhận, tính phí giao, kiểm tra tổng và xác nhận.
5. Quản trị xử lý qua nút ngay trên dòng; chỉ khi duyệt mới trừ kho, ghi giá vốn.
6. Báo cáo so sánh hai ngày giao thành công và liệt kê diễn biến bảy ngày.

Tồn các nhóm dùng chung một dòng menu, không phải mỗi nhóm một kho. Menu ngày sau
không tự kế thừa tồn; Sao chép tạo nháp với lượng 0. Đóng nhận đơn mới không tự
hủy đơn đã đặt. Đổi nhóm không đổi snapshot đơn cũ. Chức năng xin hủy đơn vẫn hoạt động.

## Cấu hình Goong

Thêm `GOONG_API_KEY=` với key thực vào `.env` cục bộ rồi khởi động lại server;
không đưa key vào Git, frontend hoặc log. Backend gọi REST Goong v2 qua HTTPS.

- [Autocomplete](https://help.goong.io/kb/rest-api-v2/autocomplete-rest-api-v2/autocomplete-v2/)
- [Place Detail](https://help.goong.io/kb/rest-api-v2/place-detail-rest-api-v2/place-detail-place-detail-v2/)
- [Directions](https://help.goong.io/kb/rest-api-v2/directions-rest-api-v2/directions-v2/)

Trong Cấu hình, tìm **96A Trần Phú, Hà Đông, Hà Nội**, xem vị trí và xác nhận rồi
lưu kho. Không tự coi một tọa độ ước đoán là vị trí đúng của số nhà. Khách cũng
chọn và xác nhận địa chỉ; server ký kết quả định vị, lưu lat/lng/placeId và version.
Đổi địa chỉ thủ công sẽ xóa định vị cũ cho tới khi xác nhận lại.

Mỗi chính sách giao riêng cần bật khoảng cách và nhập: phí cơ bản, km bao gồm,
phí mỗi km vượt, km tối đa, tiền hàng tối thiểu. Không có bảng phí kinh doanh mặc
định mới được tự động áp dụng. Công thức:

`fee = baseFee + ceil(max(0, distanceMeters / 1000 - includedKm)) * extraKmFee`

So sánh phạm vi bằng mét trước khi làm tròn km để hiển thị. Báo phí có hiệu lực
5 phút, ràng buộc user/nhóm, địa chỉ/version, giỏ/giá, chính sách/version, kho/version.
Địa chỉ ngoài phạm vi, hết hạn, không có tuyến, thiếu key hoặc hết hạn mức đều có
lỗi riêng; không dùng khoảng cách giả hay phí ước đoán để hoàn tất đơn. API bản đồ
chạy trước giao dịch khóa tồn. Nhận tập trung sinh viên giữ phí 0 theo điểm/giờ.

## Dữ liệu và API

Alembic `0003_daily_sales` bổ sung `daily_menus`, `delivery_quotes`, menu_id/cost/
archived_at trên offers, giá mặc định và audience trên products, tọa độ addresses,
cấu hình khoảng cách và cost_price_snapshot trên order_items. `db/schema.sql`
vẫn là nguồn bất biến của revision 0001; luôn chạy toàn bộ Alembic đến head.

| API `/api/v1` | Mục đích |
|---|---|
| GET /catalog/menu | Menu và sản phẩm hôm nay đã lọc quyền |
| GET /catalog/offers | Danh sách phẳng tương thích, cũng áp dụng menu/quyền |
| GET/POST /admin/menus | Liệt kê/tạo menu với nhiều items |
| GET/PATCH /admin/menus/{id} | Xem/sửa với expectedVersion và version từng dòng |
| POST /admin/menus/{id}/copy | Tạo nháp cho saleDate khác, số lượng 0 |
| GET/PATCH /admin/warehouse | Đọc/xác nhận vị trí kho bằng locationToken |
| GET /maps/search?q=… | Tìm địa chỉ có xác thực và giới hạn tốc độ |
| GET /maps/place?id=… | Lấy vị trí và token ký, hiệu lực 30 phút |
| POST /delivery/quote | Nhận addressId + items, trả id/km/phí/hạn |
| GET /admin/reports/daily?date=…&compare=… | Báo cáo ngày và so sánh |

Mutation menu có Idempotency-Key; sửa có expectedVersion. `saleDate` là ngày bắt đầu,
`opensAt` phải nằm trong ngày bắt đầu; `closesAt` có thể thuộc ngày sau. Nếu client bỏ
`closesAt`, backend mặc định hết ngày bắt đầu. Item gồm productId,
availableQty, costPrice, enabled, expectedVersion và prices[{groupId,unitPrice}].
allowedGroupIds=null nghĩa là không giới hạn thêm; mảng chọn phải có ít nhất một
nhóm đang hoạt động. Mỗi dòng bán được tùy chỉnh nhóm khi sản phẩm gốc cho phép
tất cả nhóm. Nếu sản phẩm đã giới hạn nhóm, audience của dòng bị khóa theo sản
phẩm. Quyền hiệu lực là giao của nhóm sản phẩm, dòng menu, menu ngày và nhóm có giá.

Giá nhập/giá vốn không thuộc DTO khách, sự kiện nhóm khách, snapshot hoặc replay.
Đổi audience làm thay đổi datasetEpoch, vô hiệu hóa payload catalog cũ; client có
epoch cũ nhận snapshot mới. Notification job kiểm tra lại quyền trước khi gửi.

Lãi gộp = tiền hàng đã giao − tổng giá vốn đã chụp lúc duyệt. Mỗi dòng làm tròn đến
đồng theo ROUND_HALF_UP. Phí giao không được cộng vào lãi gộp. Hàng chưa bán không
được ghi thành chi phí của lãi gộp; đây không phải báo cáo lợi nhuận ròng/kế toán.
Ngày có dòng thiếu giá vốn trả cost/grossProfit=null, không dùng 0 thay dữ liệu thiếu.

## Dọn lịch sử trước 28/10

`scripts/cleanup_sales.py` mặc định chỉ xem trước; ngày theo Asia/Ho_Chi_Minh.
Khi áp dụng phải truyền `--apply --expected-hash <previewHash>`, dừng backend chính.
Công cụ tự sao lưu DB và ảnh vào runtime/backups, lưu manifest riêng, kiểm tra hash
các đơn từ ngày mốc cùng items/history/cancellation trước và sau. Không reset ID.

Đơn trước mốc bị xóa; đợt trước mốc chỉ bị xóa khi không còn tham chiếu. Đợt liên
quan đơn được giữ/quote lịch sử được lưu trữ và đóng bán. Ledger của đợt giữ lại
không đổi lượng/balance, chỉ bỏ FK order_id trỏ tới đơn mẫu đã xóa; reference_id
lịch sử còn trong bản sao lưu và ledger. Không sinh CANCEL_RESTORE hoặc đổi tồn.
Cached response liên quan đơn đã xóa và event/outbox cũ được vô hiệu hóa; epoch mới
bắt buộc snapshot. Lần chạy lại không xóa thêm đơn/đợt đã dọn.

Không xóa tài khoản, chat, sản phẩm, địa chỉ hay các database audit của đợt kiểm thử
khác. Backup, manifest, khóa API và dữ liệu runtime được Git bỏ qua.

## Kiểm thử

Chạy toàn bộ backend trên database audit được khôi phục từ backup, rồi browser
trên HTTPS/WSS thật. Test phí/adapter dùng route tổng hợp có nhãn testOnly;
đây không phải bằng chứng Goong thực hoặc địa chỉ kho đã được xác minh. Nghiệm thu
Goong thực cần key và xác nhận vị trí; nghiệm thu hai máy cần thiết bị thứ hai trong LAN.

## Kết quả triển khai 29/10/2026

118/118 backend và 6/6 browser, build Next.js đạt. Đã dọn database chính sau sao lưu; hai đơn từ 28/10 giữ nguyên. Xem [bằng chứng](../evidence/daily-sales-20261029/summary.json). Goong thực chưa nghiệm thu vì chưa có key; người dùng đã chọn giữ Wi-Fi Public và chỉ chạy localhost, không bật truy cập LAN.
