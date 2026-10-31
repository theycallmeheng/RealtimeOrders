# Menu theo ngày, nhóm khách và lãi gộp

Quyết định trực tiếp của người dùng ngày 29/10/2026 thay thế chức năng yêu cầu
hàng/báo giá và giả định chưa dùng bản đồ trong đặc tả 22/10. Năm phần công việc
và cấu hình HTTPS/WSS LAN tiếp tục áp dụng.

## Cách dùng

1. Quản trị vào Sản phẩm: đặt giá nhập/bán mặc định, nhóm được phép mua.
2. Vào Menu theo ngày: chọn ngày bắt đầu, ngày đóng tùy chọn, nhiều món, lượng bán,
   giá nhập và giá từng nhóm; lưu nháp hoặc mở bán. Để trống ngày đóng thì đợt kết thúc
   hết ngày bắt đầu; để trống giờ đóng thì kết thúc hết ngày đã chọn. Có thể tạo
   nhiều menu cùng ngày và cùng thời gian. Mỗi đợt có ID, giá và tồn độc lập.
3. Khách vào Menu hôm nay: thêm món để mở giỏ; mua tiếp hoặc tiếp tục đặt hàng.
4. Khi thanh toán chọn địa chỉ/cách nhận, tính phí giao, kiểm tra tổng và xác nhận.
5. Quản trị xử lý qua nút ngay trên dòng; chỉ khi duyệt mới trừ kho, ghi giá vốn.
6. Báo cáo so sánh hai ngày giao thành công và liệt kê diễn biến bảy ngày.

Tồn các nhóm dùng chung một dòng menu, không phải mỗi nhóm một kho. Menu ngày sau
không tự kế thừa tồn; Sao chép tạo nháp với lượng 0. Đóng nhận đơn mới không tự
hủy đơn đã đặt. Đổi nhóm không đổi snapshot đơn cũ. Chức năng xin hủy đơn vẫn hoạt động.

## OpenStreetMap: địa chỉ và tuyến đường

Không cần API key hoặc billing. Backend mặc định dùng Nominatim để tìm/tra cứu
địa chỉ và OSRM demo server để tính khoảng cách đường đi. Có thể đổi NOMINATIM_URL
và OSRM_URL trong .env sang các dịch vụ tự quản. Tìm kiếm chỉ được gửi khi người
dùng bấm nút, không gọi gợi ý liên tục khi đang gõ. Backend giới hạn tốc độ toàn
cục tối đa một yêu cầu mỗi giây cho từng dịch vụ và cache kết quả trong bộ nhớ.

Nominatim yêu cầu User-Agent/Referer nhận diện ứng dụng, ghi nguồn dữ liệu và
giới hạn mức sử dụng; API công cộng không cho làm autocomplete. Người dùng được
thông báo rằng nội dung địa chỉ tìm kiếm được gửi tới dịch vụ công cộng. Không
gửi địa chỉ riêng tư hoặc thông tin nhạy cảm tới endpoint công cộng. Xem
[chính sách Nominatim](https://operations.osmfoundation.org/policies/nominatim/)
và [API tìm địa chỉ](https://nominatim.org/release-docs/latest/api/Search/).

OSRM demo chỉ dùng cho lưu lượng hợp lý, không thương mại, tối đa một yêu cầu
mỗi giây và không bảo đảm uptime/độ trễ. Adapter gọi profile driving; đây là
tuyến tham khảo kiểu ô tô, không khẳng định tương đương tuyến xe máy. Nếu cần
lưu lượng production, dữ liệu địa chỉ riêng tư hoặc tuyến xe máy chính xác hơn,
hãy chuyển sang nhà cung cấp có SLA hoặc tự vận hành dịch vụ OSM. Xem
[chính sách máy chủ OSRM demo](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
và [tài liệu OSRM API](https://project-osrm.org/docs/v5.24.0/api/).

Trong Cấu hình, tìm **96A Trần Phú, Hà Đông, Hà Nội**, xem vị trí và xác nhận
tọa độ kho thực tế trước khi lưu. Không tự coi một tọa độ ước đoán là vị trí đúng
của số nhà. Khách cũng chọn và xác nhận địa chỉ; server ký kết quả định vị, lưu
lat/lng/placeId và version. Đổi địa chỉ thủ công sẽ xóa định vị cũ cho tới khi
xác nhận lại.

Mỗi chính sách giao riêng cần bật khoảng cách và nhập: phí cơ bản, km bao gồm,
phí mỗi km vượt, km tối đa, tiền hàng tối thiểu. Không có bảng phí kinh doanh mặc
định mới được tự động áp dụng. Công thức:

`fee = baseFee + ceil(max(0, distanceMeters / 1000 - includedKm)) * extraKmFee`

So sánh phạm vi bằng mét trước khi làm tròn km để hiển thị. Báo phí có hiệu lực
5 phút, ràng buộc user/nhóm, địa chỉ/version, giỏ/giá, chính sách/version, kho/version.
Địa chỉ ngoài phạm vi, hết hạn, không có tuyến hoặc dịch vụ bản đồ không khả dụng
đều có lỗi riêng; không dùng khoảng cách giả hay phí ước đoán để hoàn tất đơn.
API bản đồ chạy trước giao dịch khóa tồn. Nhận tập trung sinh viên giữ phí 0 theo
điểm/giờ.

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
| GET /maps/search?q=… | Tìm địa chỉ Nominatim theo thao tác người dùng, có xác thực/giới hạn tốc độ |
| GET /maps/place?id=… | Tra vị trí OSM ID và trả token ký hiệu lực 30 phút |
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
trên HTTPS/WSS thật. Test phí/adapter dùng route tổng hợp có nhãn testOnly; đây không phải bằng chứng đã
gọi tuyến OSM thật hoặc xác minh tọa độ kho. Nghiệm thu tích hợp cần mạng Internet
và vị trí kho đã xác nhận; nghiệm thu hai máy cần thiết bị thứ hai trong LAN.

## Nghiệm thu tích hợp thật

Tính phí tuyến OSRM cần kết nối Internet và tọa độ kho đã xác nhận. Kiểm tra
hoạt động trên hai máy cần thiết bị thứ hai trong LAN; làm theo [hướng dẫn LAN](LAN.md).
Kết quả các lần chạy không được lưu trong repository. Nếu môn học yêu cầu, nhóm
tự lưu bằng chứng mới riêng cho buổi nghiệm thu.


## Giá mẫu và giá menu tự động

Giá mẫu phục vụ demo, không phải báo giá thị trường. Chạy `python scripts/sample_product_prices.py` để xem trước; thêm `--apply` để điền giá mặc định cho sản phẩm. Script sao lưu dữ liệu cũ vào `runtime/backups/`, ghi audit và cập nhật trong một giao dịch.

Menu lấy giá nhập mặc định khi chọn món. Giá nhập theo đợt vẫn sửa được; giá bán tự tính, không nhập tay. Nhóm WORKER lấy giá nhập x 1,5; STUDENT lấy giá WORKER x 0,95; VIP lấy giá WORKER x 0,90. Nhóm khác dùng giá tiêu chuẩn. Làm tròn half-up đến 1 đồng, tính giá WORKER trước rồi mới giảm giá. Backend tự tính lại khi lưu món trong menu. Giá mặc định không thay giá đợt cũ hay giá đơn đã chụp; sửa và lưu menu sẽ áp dụng giá mới cho menu đó.


## Chế độ nhóm khách của menu

`audienceMode` trong yêu cầu lưu menu nhận `MENU` (mặc định) hoặc `PRODUCT`; phản hồi trả `audience_mode`. Migration `0009` lưu chế độ này.

- `MENU`: dùng `allowedGroupIds` chung (null = tất cả nhóm). Món kế thừa, không được gửi ghi đè nhóm riêng. Khi chuyển sang chế độ này, xóa ghi đè cũ để tránh giới hạn ẩn.
- `PRODUCT`: chọn “Tùy chỉnh theo từng sản phẩm”, `allowedGroupIds` của menu phải null; từng món có thể chọn nhóm riêng. Sản phẩm đã khóa nhóm trong danh mục vẫn không cho ghi đè.

Sao chép menu giữ chế độ nhóm. Quyền mua vẫn giao cắt với giới hạn của sản phẩm, được kiểm tra trên server và không sửa các đơn đã tạo.


## Bỏ chọn món khi sửa menu

Checkbox sản phẩm không bị khóa trên menu đã lưu. Khi gửi `items` trong yêu cầu sửa menu, các món cũ không còn trong danh sách được chuyển sang `CLOSED`, giữ nguyên ID, số lượng, giá và tham chiếu đơn hàng; không hoàn kho. Mở lại biểu mẫu hiện món đó ở trạng thái chưa chọn; chọn lại dùng đúng bản ghi cũ, không tạo trùng. Sao chép menu bỏ qua các món đã ngừng bán. Menu mở cần ít nhất một món đang bán; muốn dừng tất cả, chọn Lưu và đóng bán.


## Chính sách giao theo km đã chốt

Mọi chính sách giao riêng hiện tại dùng `pricing_mode=TIERED_KM`. Tính theo quãng đường thực tế (`distance_rounding=EXACT`), không làm tròn km trước. Mốc đổi giá là 10 km; chặn giao ngoài 15 km trước khi làm tròn tiền.

| Nhóm / cách nhận | 10 km đầu | Phần vượt 10 km |
| --- | ---: | ---: |
| Sinh viên giao riêng | 3.000đ/km | 4.000đ/km |
| Người đi làm và nhóm khác giao riêng | 3.500đ/km | 5.000đ/km |
| Sinh viên nhận tập trung | Miễn phí | Không tính theo quãng đường |

Phí giao riêng = `ceil((min(km, 10) * mức đầu + max(km - 10, 0) * mức vượt) / 1000) * 1000`. Không thu thêm phí cơ bản. Ví dụ 6.100đ hoặc 6.800đ đều lên 7.000đ; 7.000đ giữ nguyên. Tuyến 12,5 km là 40.000đ cho sinh viên và 48.000đ cho nhóm khác.

Migration `0010` thêm mô hình phí theo km, `0011` thêm bước làm tròn tiền. `python scripts/configure_delivery_rates.py` xem trước; `--apply` sao lưu cấu hình và lưu các mức trên trong một giao dịch. Các giá trị này vẫn chỉnh sửa được ở tab Chính sách giao. Đơn đã tạo giữ phí đã chụp; báo phí chưa đặt đơn phải tính lại khi phiên bản chính sách thay đổi.


## Chọn điểm nhận khi thiếu số nhà

Tìm kiếm Nominatim có thể chỉ trả một đoạn đường/khu vực. Các kết quả này được gắn `approximate` để nhắc người dùng kiểm tra ghim. Người dùng cũng có thể bỏ qua tìm kiếm, mở bản đồ Leaflet, bấm hoặc kéo ghim đến đúng điểm nhận. Nút chọn tâm bản đồ hỗ trợ thao tác bằng bàn phím.

`GET /api/v1/maps/config` cung cấp tâm bản đồ theo kho và URL tile cấu hình qua `OSM_TILE_URL`. `POST /api/v1/maps/pin` xác thực phiên, CSRF, giới hạn lượt, kiểm tra tọa độ hữu hạn và trả token vị trí ký HMAC trong 30 phút. Điểm ghim lưu vào các cột latitude/longitude hiện có, placeId dạng `pin:lat,lon`; không reverse-geocode mỗi lần di chuyển ghim.

Địa chỉ chi tiết được giữ riêng, không bị tên đường của bản đồ ghi đè. Phí giao tiếp tục do server tính qua OSRM từ tọa độ đã xác nhận. Tile chỉ tải khi người dùng mở bản đồ, không tải hàng loạt; hiển thị attribution theo [OSM Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/). Các giới hạn tìm kiếm Nominatim vẫn giữ nguyên.


## Tìm số nhà: danh sách xác nhận, Photon và Nominatim

Migration `0012` thêm `verified_locations`. Quản trị tạo/sửa/ngừng gợi ý địa chỉ công cộng trong Cấu hình. Mỗi điểm có nhãn, số nhà, đường, tên gọi khác, tọa độ và phiên bản. Thêm mới cần token ghim đã xác nhận; sửa và ngừng cần expectedVersion. Không tự nhập hay chia sẻ địa chỉ riêng của khách.

Các API quản trị: `GET/POST /api/v1/admin/maps/verified`, `PATCH/DELETE /api/v1/admin/maps/verified/{id}`. Chỉ ADMIN được dùng; có CSRF, audit và kiểm tra phiên bản. Ngừng gợi ý không xóa đơn hay địa chỉ khách đã lưu. Chạy `python scripts/register_warehouse_address.py` sau khi xác nhận kho ở Học viện để đăng ký alias 96A Trần Phú; script không đổi tọa độ kho và không tạo lặp.

`GET /api/v1/maps/search?q=...` chuẩn hóa dấu/Unicode để tìm alias trong MySQL. Khớp alias chính xác thì không gọi dịch vụ ngoài. Nếu chưa có, tìm Photon ưu tiên quanh kho; gọi Nominatim dự phòng khi không có kết quả khớp số nhà. Khớp nội bộ một phần vẫn kết hợp kết quả ngoài. Xếp theo mức khớp, sau đó khoảng cách thẳng tới kho; khoảng cách này chỉ xếp gợi ý, không tính phí. Khử trùng các kết quả cùng OSM ID.

Kết quả trả source, houseNumber, street, matchType: VERIFIED (quản trị xác nhận), HOUSE_NUMBER (số nhà và tên đường khớp chuỗi), NEARBY (gần đúng), STREET (đường/khu vực). HOUSE_NUMBER không phải bảo đảm đúng khu vực/cổng; người dùng vẫn kiểm tra ghim. Không nội suy hay tự gán số nhà vào kết quả đường.

Photon có cache 10 phút, giới hạn 1 request/giây cho toàn server; Nominatim giữ cùng giới hạn riêng, không autocomplete. Cấu hình `PHOTON_URL` để chuyển sang máy chủ tự quản. Mã Photon dạng `photon:W123`; kết quả hết cache sau 1 giờ yêu cầu tìm lại. Mã nội bộ `local:<uuid>` đọc MySQL mỗi lần xác nhận, kể cả sau restart và không dùng điểm đã ngừng.

Kiểm thử tập trung: `cd backend; python -m pytest tests/test_geocoding.py tests/test_map_pin.py tests/test_delivery_tiers.py -q`. Kết quả tìm thực tế phụ thuộc dữ liệu của nhà cung cấp. [Photon API](https://github.com/komoot/photon/blob/master/docs/api-v1.md), [giới hạn demo Photon](https://github.com/komoot/photon#demo-server), [chính sách Nominatim](https://operations.osmfoundation.org/policies/nominatim/).


## Hết hàng, mặt hàng chưa mở bán và gợi ý

- `effective_status=SOLD_OUT` (Đã bán hết) là trạng thái tính từ tồn của các dòng sản phẩm đang bật, còn hoạt động trong menu. Không ghi đè trạng thái lưu `OPEN` bằng `CLOSED`. Thời gian chưa mở/hết hạn và đóng thủ công vẫn được ưu tiên.
- Khi không còn món nào còn tồn, không thể tạo đơn mới với số lượng dương. Bổ sung hoặc hoàn kho tự đưa đợt về trạng thái hiệu lực OPEN nếu vẫn trong thời gian bán; không mở lại đợt đóng tay/hết hạn. Không tự hủy đơn chờ đã có.
- Menu khách có mục Đang mở bán và Mặt hàng sắp mở bán. `GET /api/v1/catalog/upcoming` chỉ trả sản phẩm hoạt động, đúng nhóm khách và chưa nằm trong bất kỳ đợt bán không lưu trữ nào (kể cả đợt nháp hoặc lịch sử). Không trả giá vốn/giá bán dự kiến hoặc cho đặt món chưa mở; khách có thể đăng ký thông báo bằng luồng theo dõi hiện có.
- Khung Gợi ý hôm nay ở đầu menu lấy ngẫu nhiên tối đa năm dòng hàng đang mở, đúng quyền xem và còn tồn. Chỉ hiển thị giá đang áp dụng, không gắn nhãn giảm giá giả. Khách có thể thêm vào giỏ hoặc đóng khung; lựa chọn đóng được giữ khi reload trong cùng phiên trình duyệt và xóa khi bấm đăng xuất.


## Nhiều đợt đồng thời

Cho phép các đợt OPEN trùng toàn bộ hoặc một phần thời gian, nhưng không được trùng sản phẩm đang bật trong các đợt đó. Quy tắc áp dụng cả khi mở bản nháp, mở lại đợt hoặc sửa lịch/thêm món; không phân biệt nhóm khách. Khóa dòng sản phẩm trước khi kiểm tra để hai yêu cầu đồng thời không cùng mở được một sản phẩm. Đợt CLOSED, DRAFT, dòng món CLOSED hoặc đã lưu trữ không gây xung đột. Kho hết không gỡ giới hạn vì hàng có thể được hoàn/bổ sung. Hai khung giờ nối tiếp nhau được phép. Lỗi PRODUCT_ALREADY_OPEN (409) nêu tên món cần bỏ hoặc đổi lịch. Mỗi dòng bán có offer ID riêng; giỏ hàng, giá, trừ/hoàn kho vẫn tham chiếu offer ID, không gộp theo product ID. Đóng hoặc bán hết một đợt không làm đóng đợt khác. Menu khách hiển thị tất cả dòng bán được phép xem trong các đợt đang mở, kèm mã đợt rút gọn và thời gian để phân biệt. `GET /api/v1/catalog/menu` trả danh sách `menus`; trường `menu` giữ menu được phép xem có giờ mở gần nhất để tương thích client cũ. Mỗi đợt vẫn yêu cầu giờ đóng sau giờ mở.


## Báo cáo tháng và nhật ký

- Báo cáo Theo ngày chỉ hiển thị 7 ngày liên tiếp, kết thúc ở ngày báo cáo được chọn; ngày so sánh không làm dài thêm bảng. Theo tháng hiển thị tổng tháng, đối chiếu một tháng khác và chi tiết đủ 28–31 ngày của tháng đã chọn. Xuất CSV theo đúng bảng đang xem. Chỉ đơn DELIVERED được tính theo ngày giao thành công tại Việt Nam. Thiếu giá vốn ở bất kỳ dòng nào thì tổng giá vốn/lãi gộp của kỳ đó là chưa đủ dữ liệu.
- API tháng: `GET /api/v1/admin/reports/monthly?month=2026-10&compare=2026-09`; bỏ compare thì đối chiếu tháng trước. Không tính tỷ lệ phần trăm khi kỳ đối chiếu bằng 0.
- Ba API nhật ký `/admin/audit`, `/admin/inventory-movements`, `/admin/moderation/violations` nhận `startDate`, `endDate` dạng YYYY-MM-DD (bao gồm toàn bộ ngày cuối theo giờ Việt Nam), và `page` bắt đầu từ 0. Mỗi trang tối đa 100 dòng, sắp theo thời điểm và ID giảm dần. Chỉ quản trị được đọc.
- Nhật ký thêm tên người thực hiện/đối tượng, dịch mã thao tác sang tiếng Việt và hiển thị các trường thay đổi. Dữ liệu gốc trước/sau vẫn giữ để mở xem khi cần; không sửa hoặc xóa lịch sử nhật ký.
