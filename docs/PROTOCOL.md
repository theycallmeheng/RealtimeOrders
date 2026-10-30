# Hợp đồng HTTP và WebSocket v1

Đây là hợp đồng đề xuất trước triển khai. Một origin, prefix `/api/v1`, socket
`/ws`. HTTPS/WSS là cấu hình demo triển khai; HTTP/WS chỉ dùng phát triển
loopback có nhãn rõ, không được trình bày như kiểm thử TLS.

## 1. Quy ước chung

- ID là UUID dạng chuỗi; tiền/số lượng và seq/version truyền chuỗi để tránh
  float hoặc giới hạn số nguyên JavaScript. Thời gian ISO 8601 UTC, ngày bán DATE
  theo Asia/Ho_Chi_Minh. UI định dạng tiếng Việt, không đổi ý nghĩa giá trị.
- Session bằng cookie HttpOnly; gọi HTTP cùng origin có credentials. Mutation
  có CSRF header; khóa Idempotency-Key UUID bắt buộc cho đơn/duyệt/hủy/chuyển yêu
  cầu thành đơn. Frontend giữ nguyên key khi retry cùng hành động.
- Mutation có `expectedVersion` khi sửa tài nguyên đã có. Không dùng GET để đổi
  tồn hoặc đổi trạng thái. Cursor phân trang là opaque, limit mặc định 20, tối đa 100.
- JSON lỗi gồm `code`, `message`, `requestId`, `details` được phép công bố;
  không kèm traceback, password, token, raw từ vi phạm hay dữ liệu khách khác.
- Role, trạng thái đơn và trạng thái user dùng enum viết HOA như schema SQL.

```json
{
  "code": "INSUFFICIENT_STOCK",
  "message": "Đơn chưa được duyệt vì một mặt hàng không đủ số lượng.",
  "requestId": "54c13cca-7e2d-40ae-a7a5-1c9268d13a53",
  "details": {"items": [{"offerId": "offer-uuid", "requestedQty": "7.000", "availableQty": "3.000"}]}
}
```

Ví dụ dùng `offer-uuid`, `order-uuid` là ký hiệu minh họa, phải thay bằng UUID
hợp lệ khi làm fixture hoặc gọi API thật.

## 2. Endpoint

| Method | Path | Vai trò / tác dụng |
|---|---|---|
| POST | /auth/registration/otp | Chưa đăng nhập; xin OTP Zalo trước, có giới hạn |
| POST | /auth/registration/sms-fallback | Chọn gửi SMS thay mã Zalo; tối đa một lần cho challenge |
| POST | /auth/registration/verify | Xác minh OTP mới nhất, lấy ticket hoàn tất một lần |
| POST | /auth/register | Ticket + mật khẩu + tên; tạo user, session |
| POST | /auth/login | SĐT/email đã xác minh + mật khẩu; cookie phiên |
| GET | /auth/session | User/role/nhóm, hạn phiên, CSRF token; Cache-Control no-store |
| POST | /auth/logout | Thu hồi phiên hiện tại và đóng WSS |
| POST | /auth/password-reset/otp | OTP SMS cho SĐT đã đăng ký; trả thông báo không tiết lộ tài khoản |
| POST | /auth/password-reset/confirm | Ticket hợp lệ + mật khẩu mới; thu hồi các phiên cũ |
| POST | /auth/email/challenge | Đã đăng nhập; xin xác minh email tùy chọn |
| POST | /auth/email/verify | Gắn email duy nhất sau xác minh |

| GET/PATCH | /me | Hồ sơ; tên được kiểm duyệt |
| GET/POST | /me/addresses | Địa chỉ của chính mình; max 3 |
| PATCH/DELETE | /me/addresses/{id} | Sửa/xóa mềm địa chỉ thuộc mình |
| PUT | /me/default-address | Chọn default thuộc chính mình |
| GET | /catalog/offers | Đợt đang bán, giá nhóm hiện tại và thống kê |
| GET | /delivery/options | Các phương án theo address/cart, phiên bản chính sách |
| POST | /orders | Tạo PENDING, chụp giá/phí, không trừ kho |
| GET | /orders | Danh sách của khách; admin xem qua /admin/orders |
| GET | /orders/by-client-id/{id} | Tra kết quả một lần gửi của chính mình sau mất response/reload |
| GET | /orders/{id} | Chủ đơn hoặc admin |
| POST | /orders/{id}/cancel | Khách hủy PENDING |
| POST | /orders/{id}/cancellation-requests | Khách xin hủy APPROVED/PREPARING |
| GET/POST | /product-requests | Xem/gửi yêu cầu hàng của mình |
| POST | /product-requests/{id}/accept-quote | Khách đồng ý đúng phiên bản báo giá |
| POST | /product-requests/{id}/convert | Tạo một đơn PENDING từ báo giá đã chấp thuận |
| GET | /conversations/me/messages | Lịch sử chat của chính khách, phân trang |
| POST | /media | Upload một ảnh, trả assetId khi READY |
| GET | /media/{id} | Kiểm tra quyền theo mục đích/quan hệ ảnh |
| GET | /notifications | Thông báo của chính mình |
| POST | /notifications/{id}/read | Đánh dấu đã đọc, idempotent |
| PUT/DELETE | /subscriptions/products/{id} | Bật/tắt quan tâm sản phẩm |
| GET/POST/PATCH | /admin/catalog/* | Danh mục, đơn vị, sản phẩm, đợt, giá nhóm |
| POST | /admin/offers/{id}/inventory-adjustments | Sửa tồn có lý do, ledger và version |
| GET/POST/PATCH | /admin/delivery/* | Khu vực, chính sách và điểm/khung giao |
| GET/PATCH | /admin/users/* | Nhóm/trạng thái, khóa/mở/xóa mềm, audit |
| GET | /admin/orders | Bộ lọc trạng thái/ngày/nhóm, phân trang |
| POST | /admin/orders/{id}/approve | Duyệt toàn bộ, transaction và idempotency |
| POST | /admin/orders/{id}/reject | Từ chối PENDING, không trừ kho |
| POST | /admin/orders/{id}/transition | PREPARING/SHIPPING/DELIVERED theo state machine |
| POST | /admin/cancellation-requests/{id}/decision | Chấp thuận hoặc từ chối hủy; nếu chấp thuận thì hoàn kho |
| GET/PATCH | /admin/product-requests/* | Tiếp nhận/từ chối, trạng thái có version |
| POST | /admin/product-requests/{id}/quotes | Báo giá có hạn và phiên bản |
| GET | /admin/conversations/{id}/messages | Lịch sử hội thoại được phép |
| GET/POST/PATCH/DELETE | /admin/moderation/rules/* | Danh sách và trạng thái từ cấm |
| GET | /admin/moderation/violations | Nhật ký vi phạm có quyền riêng |
| GET | /admin/reports | Theo ngày/tháng, thời gian tính trong múi giờ kinh doanh |
| GET | /admin/audit | Nhật ký quản trị, lọc/phân trang |

OTP đăng ký trả challengeId, channel, deliveryStatus, expiresIn,
fallbackAfterSeconds, fallbackAvailable và cờ demo. channel là zalo, sms hoặc
demo; chỉ OTP demo trong DEMO_MODE mới kèm demoCode. Nếu Zalo nhận yêu cầu, có
thể chọn SMS sau 60 giây; nếu Zalo từ chối, nút SMS được bật ngay.
POST /auth/registration/sms-fallback nhận challengeId, tạo OTP mới và vô hiệu
hóa challenge cũ trước khi gửi SMS. Mỗi challenge Zalo chỉ được chuyển sang SMS
một lần. Khôi phục mật khẩu không dùng luồng Zalo này.

CRUD con cụ thể được đóng thành OpenAPI khi triển khai; dấu `*` ở bảng là nhóm
endpoint thiết kế, không phải một route wildcard dùng để bỏ qua phân quyền.

`POST /admin/products` không nhận SKU do trình duyệt tự chọn. Server cấp mã
SKU tăng dần và trả lại trong sản phẩm đã tạo; `PATCH /admin/products/{id}` giữ
nguyên mã đã cấp.

`POST/PATCH /admin/products` nhận danh sách ảnh có thứ tự `images`, tối đa 5
phần tử. Mỗi phần tử phải có đúng một trường: `{"assetId":"UUID"}` cho tệp
đã tải qua `/media`, hoặc `{"url":"https://..."}` cho ảnh công khai. Server
kiểm tra chủ sở hữu asset; URL chỉ nhận HTTPS, lưu tại `product_images.source_url`
và không được server tải xuống. `GET /admin/products` trả `asset_id`,
`source_url` và `position`; `/catalog/offers` chỉ trả danh sách ảnh của sản phẩm
mà khách được phép xem. Giá trị ảnh cũ dạng `assetIds` vẫn được nhận để tương thích.
Database mới cũng có `source_url` sau khi `setup.ps1` chạy Alembic tới `head`
(revision `0007`).

`GET/POST/PATCH/DELETE /admin/config/groups` quản lý nhóm khách hàng; DELETE là
ngừng sử dụng mềm để giữ liên kết đơn hàng. `WORKER` không thể ngừng dùng vì là
nhóm đăng ký mặc định; `STUDENT` chỉ ngừng được sau khi tắt chính sách giao tập
trung. Mỗi item của menu nhận `allowedGroupIds`: cho phép NULL hoặc danh sách nhóm
chỉ khi sản phẩm gốc mở cho tất cả nhóm; với sản phẩm đã giới hạn, server từ chối
override. Khách chỉ nhận item nếu thuộc giao của các audience sản phẩm, item và menu.

```json
{
  "clientOrderId": "4c8e7642-ea8f-43ce-a2d2-4c6cc307f39c",
  "addressId": "address-uuid",
  "delivery": {"method": "INDIVIDUAL", "policyId": "policy-uuid", "expectedVersion": "3"},
  "items": [{"offerId": "offer-uuid", "quantity": "0.500", "expectedPriceVersion": "8"}],
  "note": "Gọi trước khi giao"
}
```

Server không nhận `userId`, `groupId`, `unitPrice`, `shippingFee`, `total` làm
giá trị có thẩm quyền trong request này. Khi giá/phí đổi: 409 REQUOTE_REQUIRED,
gửi phương án mới cho đúng khách; không tạo đơn và không tự chấp nhận giá mới.

Frontend có thể giữ clientOrderId của lần gửi chưa rõ kết quả qua reload để tra
cứu; không lưu session token/OTP hoặc địa chỉ đầy đủ vào localStorage. Cùng ID
nhưng body khác là conflict. Quyết định yêu cầu hủy gửi `expectedVersion` của
request và `expectedOrderVersion` của order, kiểm tra cả hai dưới lock.

## 3. Envelope WebSocket

JSON text, trường `v=1`, `type`, `requestId` cho command, `payload` object.
Ảnh không nằm trong frame. Session cookie và Origin được kiểm tra trước accept.
Timeout nhận HELLO đề xuất 5 giây, heartbeat 15 giây, stale sau 45 giây,
reconnect 1/2/4/8/15 giây có jitter. Cấu hình này chưa là kết quả hiệu năng.

```json
{
  "v": 1,
  "type": "HELLO",
  "requestId": "65024ce1-c088-4b15-a96a-d65d9734c121",
  "payload": {"hasState": true, "cursors": {"catalog:group-uuid": "123", "user:user-uuid": "98"}}
}
```

Server cấp topic dựa trên DB, không tin userId/role/group/topic do client tự
khai. Topic chưa có quyền bị từ chối, không trả head hoặc nội dung của topic đó.

| Hướng | Type | Nội dung |
|---|---|---|
| C→S | HELLO | Phiên bản/cursor/model có sẵn |
| S→C | WELCOME | Topic được phép, heartbeat, server time và giới hạn |
| S→C | SYNC_BEGIN | syncId, mode SNAPSHOT/REPLAY và heads ranh giới |
| S→C | SNAPSHOT_CHUNK | syncId, index, working-set DTO; chunk mục tiêu 32 KiB |
| S→C | EVENT / EVENT_BATCH | Topic/seq/eventId/type/entityVersion và payload |
| S→C | SYNC_END | syncId, heads đã hoàn tất; client mới đổi sang connected |
| C→S | CHAT_SEND | ConversationId, clientMessageId, text, assetIds |
| S→C | ACK | requestId/clientMessageId, messageId và kết quả đã lưu |
| C↔S | PING / PONG | Giữ kết nối; không gia hạn thời gian hoạt động |
| C→S | SESSION_ACTIVITY | Hoạt động tương tác, throttle ≤1/phút, không vượt hạn tuyệt đối |
| S→C | SESSION_REVOKED | Đóng phiên, xóa trạng thái riêng và quay về đăng nhập |
| C→S | RESYNC_REQUEST | Phát hiện gap/không còn model; xin đồng bộ lại |
| S→C | ERROR | Code và requestId, không tiết lộ dữ liệu cấm |

```json
{
  "v": 1,
  "type": "EVENT",
  "topic": "catalog:group-uuid",
  "seq": "124",
  "eventId": "949ca39f-3a13-4c26-a2ed-aa51611e2bc4",
  "eventType": "OFFER_UPDATED",
  "entityVersion": "19",
  "payload": {"offerId": "offer-uuid", "availableQty": "3.000", "pendingQty": "6.000", "unitPrice": "120000", "priceVersion": "8"}
}
```

Các event nghiệp vụ: OFFER_PUBLISHED, OFFER_UPDATED, OFFER_CLOSED,
ORDER_CREATED, ORDER_STATUS_CHANGED, CANCELLATION_UPDATED, REQUEST_UPDATED,
MESSAGE_CREATED, NOTIFICATION_CREATED, NOTIFICATION_READ, ACCOUNT_CHANGED.
Thông báo có ID riêng, không nhân đôi vì event được phát lại.

## 4. Quy tắc client

- Chỉ nâng cursor sau khi reducer áp dụng thành công. Seq ≤ cursor bỏ qua;
  seq > cursor+1 đánh dấu thiếu và resync. Snapshot thay working set một lần
  sau SYNC_END hợp lệ; không trộn snapshot nửa chừng vào model đang hiển thị.
- Khi offline: giữ nội dung đã nhận có nhãn cũ; không nhận thêm đặt hàng/chat
  mới. HTTP/WSS đã gửi chưa rõ kết quả được retry bằng đúng key/client ID.
- ACK không làm client tự trừ kho. State cuối lấy từ response/event chính thức.
- `entityVersion` tránh response HTTP cũ ghi đè event mới hơn. Chưa tải entity
  thì invalidate/fetch theo version; cursor vẫn xử lý đủ event của topic.
- Group/role đổi: thu hồi session, bỏ topic cũ và tải lại; không replay topic
  cũ chỉ vì client vẫn giữ cursor trong bộ nhớ.

## 5. Lỗi và giới hạn

HTTP: 400 sai cú pháp, 401 phiên, 403 quyền, 404 tài nguyên không được tiết lộ,
409 xung đột/thiếu kho/giá đổi, 413 ảnh lớn, 422 validation, 429 giới hạn,
503 DB/provider/bộ phận dịch vụ chưa sẵn sàng. Message hướng người dùng bằng
tiếng Việt; code ổn định cho client và kiểm thử.

Code chính: OTP_INVALID, OTP_EXPIRED, OTP_RATE_LIMITED, IDENTIFIER_IN_USE,
SESSION_EXPIRED, FORBIDDEN, ADDRESS_LIMIT, INVALID_QUANTITY, REQUOTE_REQUIRED,
INSUFFICIENT_STOCK, INVALID_TRANSITION, VERSION_CONFLICT, QUOTE_EXPIRED,
IDEMPOTENCY_CONFLICT, CANCELLATION_OPEN, MESSAGE_REJECTED, INVALID_MEDIA,
SYNC_REQUIRED, STORAGE_UNAVAILABLE, SMS_UNAVAILABLE.

WSS frame >64 KiB đóng 1009; dữ liệu/quyền vi phạm nghiêm trọng đóng 1008;
receiver quá tải đóng 1013. JSON hỏng/command lỗi trả ERROR nếu còn an toàn để
giữ kết nối. Queue 128 frame/512 KiB; lưu log metadata lỗi, không dump nội dung
private. Các giới hạn phải áp dụng cả proxy và ứng dụng, không chỉ giao diện.

## 6. Hợp đồng bản thực hiện

Bổ sung 24/10/2026: `POST /me/addresses` và `POST /product-requests` nhận
`Idempotency-Key` để chống tạo trùng khi mất xác nhận; cùng actor/scope/key và
body trả lại cùng kết quả, body khác trả 409 `IDEMPOTENCY_CONFLICT`. Header này
chưa bắt buộc trên hai route để giữ tương thích client cũ; frontend luôn gửi.
`processingLocked`, `makeDefault` và quyết định `accept` chỉ nhận JSON boolean.
Socket chỉ nhận JSON dạng text; frame nhị phân trả `INVALID_MESSAGE` rồi đóng
với mã 1008. Danh sách dòng đơn/giá nhóm và ID ảnh sai kiểu trả HTTP 400.

OpenAPI thực tại `/api/openapi.json`, giao diện đọc tại `/api/docs` qua proxy.
Đây là nguồn route chính xác; body JSON của các thao tác ở dưới và trong mã test.
Đơn vị số lượng và tiền là chuỗi thập phân, version/seq là chuỗi số nguyên.

Các nhóm cấu hình thực: `/api/v1/admin/config/groups`, `categories`, `units`,
`zones`, `policies`, `pickup-slots`, `moderation-rules`. GET/POST trên collection,
PATCH/DELETE với `/{id}`. DELETE chỉ vô hiệu hóa loại có `active`; không xóa FK.
Khóa/xóa mềm khách dùng PATCH `/admin/users/{id}` với `expectedVersion`, `status`.
Quản trị lấy địa chỉ/chính sách khách để báo giá tại `/admin/users/{id}/delivery-context`.

Ví dụ tạo đơn, header `Idempotency-Key: <UUID>` và `X-CSRF-Token: <session csrf>`:

```json
{"clientOrderId":"UUID","addressId":"UUID","deliveryMethod":"INDIVIDUAL",
 "policyVersion":"1","note":"Giao buổi chiều",
 "items":[{"offerId":"UUID","quantity":"0.300","expectedPriceVersion":"1"}]}
```

Giao tập trung thêm `pickupSlotId`/`pickupSlotVersion`. Giá/tổng/groupId do client
tự thêm không có quyền quyết định. `POST /admin/orders/{id}/approve` dùng body
`{"expectedVersion":"1"}`; `transition` thêm `status`. Khách xin hủy tại
`/orders/{id}/cancellation-requests`; admin quyết định tại
`/admin/orders/{id}/decide-cancel`, body thêm `accept` boolean và `reason`.

Catalog event áp dụng trực tiếp trong giao diện:

```json
{"v":1,"type":"EVENT","topic":"catalog:GROUP_UUID","seq":"12",
 "eventId":"UUID","eventType":"CATALOG_CHANGED","entityId":null,
 "entityVersion":null,"payload":{"offers":[{"id":"UUID","version":"3",
 "unit_price":"28000","price_version":"2","available_qty":"12.500"}],
 "removedOfferIds":[]}}
```

`offers` thực tế có cùng các trường canonical của `/catalog/offers`, chỉ giá
đúng nhóm. Ví dụ lược các trường tên/đơn vị để ngắn. Sự kiện cấu hình rộng dùng
`{"refresh":true}`; admin nhận invalidation riêng, không phát giá nhóm khác cho khách.
Ảnh upload multipart tại `/media`, trường `file` và `purpose=CHAT|PRODUCT`;
chat dùng `assetIds`, không Base64 trong WSS. URL ảnh sản phẩm không đi qua
endpoint upload và được trình duyệt tải trực tiếp từ host HTTPS trong `source_url`.
HTTP gửi chat với `clientMessageId`
được chống trùng như WSS CHAT_SEND.

Code thực dùng RATE_LIMITED, PHONE_USED, INVALID_NUMBER, INVALID_STEP,
INVALID_STATE, INVALID_IMAGE, RETRY_REQUIRED cùng các code quyền/phiên/giá trong
phần trên. Không yêu cầu client phụ thuộc các tên code đề xuất chưa xuất hiện
trong implementation. Lỗi luôn có `error.code`, `error.message`, `requestId`.


## Bổ sung 29/10/2026: menu ngày và phí giao

Hợp đồng bổ sung ở DAILY_SALES.md thay thế quy trình product-requests. GET/POST các
API `/product-requests` và `/admin/product-requests` trả 410 FEATURE_RETIRED.
HELLO có `datasetEpoch`; SYNC_END trả epoch hiện tại. Thiếu/khác epoch sẽ nhận
snapshot thay vì replay để không phục hồi catalog bị thu hồi quyền hoặc dữ liệu đã dọn.
Đặt giao riêng bắt buộc `deliveryQuoteId`; trả REQUOTE_REQUIRED nếu phí hết hạn hoặc
không còn khớp địa chỉ/giỏ/nhóm/chính sách/kho. Giá vốn chỉ thuộc DTO quản trị.
