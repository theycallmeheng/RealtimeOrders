# RealtimeOrders — Hệ thống đặt và điều phối bán hàng thời gian thực

Đồ án môn **Lập trình mạng**, Nhóm **15** · Giảng viên: **Ngô Văn Quyền**.

RealtimeOrders là ứng dụng web client–server giúp khách hàng xem menu theo ngày, đặt nhiều mặt hàng và theo dõi đơn; người bán quản lý sản phẩm, tồn kho, đơn và giao hàng. Backend là nơi quyết định quyền, giá, phí và trạng thái. **Đơn đang chờ không giữ hàng; chỉ khi quản trị duyệt, server mới trừ tồn.**

## Bài toán và mục tiêu

Trong mô hình bán hàng theo nhóm ở trường học, người bán thường mở nhiều mặt hàng trong các khung giờ khác nhau, giới hạn số lượng và áp dụng giá hoặc cách giao riêng cho từng nhóm khách. Nếu nhận đơn qua tin nhắn hoặc bảng tính, người bán khó theo dõi hàng còn lại khi nhiều khách cùng đặt, khách dễ nhìn nhầm giá/đợt bán, còn trạng thái đơn không đến mọi người kịp thời.

RealtimeOrders mô phỏng quy trình này bằng ứng dụng client–server cho một người bán. Mục tiêu là:

- **Quản lý các đợt bán rõ ràng:** mở nhiều đợt theo thời gian, chọn nhiều sản phẩm, kiểm soát tồn riêng và ngăn cùng một sản phẩm xuất hiện trong các đợt đang chồng lịch.
- **Phục vụ đúng nhóm khách:** hiển thị sản phẩm, giá và cách giao theo nhóm được cấu hình; máy chủ kiểm tra lại quyền và giá khi nhận đơn.
- **Giữ dữ liệu đơn hàng và tồn kho nhất quán:** đơn chờ chưa giữ hàng; khi duyệt, máy chủ kiểm tra toàn bộ mặt hàng và cập nhật tồn trong một giao dịch để tránh bán vượt kho hoặc trừ lặp khi gửi lại yêu cầu.
- **Cập nhật và phục hồi qua mạng:** phát thay đổi đơn/menu qua WebSocket; sau tải lại trang hoặc mất kết nối, client nhận các sự kiện còn thiếu hoặc tải lại snapshot.
- **Hỗ trợ vận hành và đánh giá:** áp dụng chính sách giao riêng theo quãng đường hoặc giao tập trung; lưu giá vốn tại thời điểm duyệt để báo cáo doanh thu, giá vốn và lãi gộp theo ngày/tháng.

### Trọng tâm cải tiến trong phạm vi đồ án

Các hệ thống đặt hàng trực tuyến đã có sẵn những chức năng như giỏ hàng, quản lý tồn và cập nhật trạng thái. Vì vậy nhóm **không tuyên bố tạo ra công nghệ hay thuật toán mới**. Phần nhóm tập trung xây dựng là cách kết hợp các chức năng đó theo nghiệp vụ bán hàng theo nhóm trong trường:

- Từ một danh sách món chung thành các đợt bán có lịch riêng, tồn riêng, nhiều sản phẩm và quyền xem/mua theo nhóm.
- Từ kiểm tra tồn đơn giản thành luồng duyệt có kiểm tra đồng thời, cập nhật tồn, ghi biến động kho và chống xử lý trùng.
- Từ thông báo cập nhật đơn thành luồng sự kiện có lưu bền vững, thứ tự theo phiên bản và đồng bộ lại sau khi client kết nối lại.
- Từ một mức giao hàng cố định thành chính sách có giao tập trung miễn phí cho sinh viên và giao riêng tính theo tuyến đường, giới hạn quãng đường.

Nhóm có thể chứng minh các mục tiêu này bằng demo hai trình duyệt: tài khoản thuộc nhóm khác nhau thấy đúng giá/sản phẩm; nhiều đơn cạnh tranh mặt hàng cuối không làm tồn âm; thay đổi được cập nhật trực tiếp và client bắt kịp sau khi kết nối lại. Đây là cải tiến về **mô hình nghiệp vụ và cách tích hợp trong đồ án**, không phải khẳng định hệ thống vượt trội hơn các nền tảng thương mại đang vận hành.

Phạm vi hiện tại là ứng dụng hỗ trợ một người bán, gồm hai vai trò chính: khách hàng và quản trị. Hệ thống chưa có thanh toán trực tuyến, kết nối đơn vị vận chuyển, đổi trả sau khi giao thành công hoặc nhiều máy chủ ứng dụng.

## Thành viên

| Họ tên | MSSV |
| --- | --- |
| Nguyễn Đức Hưng | B23DCCN368 |
| Đỗ Quang Thiệp | B23DCCN787 |
| Vũ Đức Mạnh | B23DCCN535 |
| Lê Nguyễn Hồng Quân | B23DCCN675 |
| Trịnh Văn Hào | B23DCCN284 |

Phân công chi tiết được trình bày trong báo cáo của nhóm.

## Chức năng

**Khách hàng**

- Đăng ký bằng số điện thoại và OTP; email là tùy chọn. Môi trường demo có thể trả mã thử để kiểm tra luồng.
- Xem menu đang mở theo nhóm khách hàng; tìm/lọc mặt hàng, xem đơn vị, giá và lượng còn.
- Thêm món vào giỏ, chọn địa chỉ/cách nhận hàng, xem tổng tiền và gửi đơn.
- Theo dõi trạng thái đơn, thông báo, hội thoại riêng và mặt hàng quan tâm.
- Hủy đơn đang chờ; gửi yêu cầu hủy đơn đã duyệt hoặc đang chuẩn bị để quản trị quyết định.

**Quản trị**

- Quản lý danh mục, đơn vị, SKU tự cấp, ảnh sản phẩm, giá và nhóm được phép mua.
- Tạo menu theo ngày với nhiều sản phẩm; có thể mở nhiều đợt trong ngày và cấu hình thời gian đóng.
- Quản lý chính sách giao, nhóm khách hàng, tài khoản, đơn, hội thoại, kiểm duyệt và báo cáo.
- Duyệt, từ chối, chuẩn bị, bàn giao và xác nhận giao đơn. Đơn đã duyệt chỉ hoàn kho khi quản trị chấp thuận yêu cầu hủy.

**Tính năng cần cấu hình dịch vụ ngoài**

- Tìm địa chỉ ưu tiên danh sách công cộng đã xác nhận, sau đó Photon/Nominatim; tính quãng đường qua OSRM, không cần API key; cần vị trí kho đã xác nhận. Dịch vụ công cộng có giới hạn lưu lượng, tuyến OSRM là mô hình ô tô tham khảo.
- Gửi OTP Zalo/SMS và email thật cần thông tin nhà cung cấp hợp lệ. Cấu hình mẫu bật chế độ demo; chưa có cấu hình không đồng nghĩa với đã kiểm chứng gửi tin thật.
- Chức năng yêu cầu hàng/báo giá đã được gỡ khỏi phạm vi; API cũ trả HTTP 410.

## Kiến trúc

```mermaid
flowchart LR
  C[Trình duyệt khách hàng] <-->|HTTPS REST / WSS| P[Proxy TLS :3443]
  A[Trình duyệt quản trị] <-->|HTTPS REST / WSS| P
  P -->|/api/* và /ws| F[FastAPI :8000]
  P -->|Trang web| N[Next.js :3000]
  F --> D[(MySQL InnoDB)]
  D --> O[Event và outbox bền vững]
  O --> H[WebSocket hub trong tiến trình]
  H --> P
```

- **Client:** trình duyệt chạy giao diện Next.js; khách và quản trị dùng chung ứng dụng nhưng có quyền khác nhau.
- **Proxy:** Node.js kết thúc TLS tại cổng 3443; chuyển `/api/*` và `/ws` đến backend, các yêu cầu trang đến Next.js.
- **Backend:** FastAPI/Python xử lý xác thực, phân quyền và nghiệp vụ. Trình duyệt không kết nối MySQL trực tiếp.
- **Database:** MySQL/InnoDB là nguồn dữ liệu chính; Alembic quản lý schema. Ảnh tải lên nằm trong thư mục riêng trên server.
- **Realtime:** backend lưu sự kiện/outbox cùng giao dịch nghiệp vụ; sau commit, hub phát theo topic tới các kết nối có quyền.

Cấu hình mặc định chỉ nghe trên máy cục bộ: mở `https://localhost:3443`; backend và frontend nội bộ lần lượt ở cổng 8000 và 3000; MySQL mặc định ở `127.0.0.1:3306`. Tùy chọn LAN được mô tả ở mục chạy trong cùng mạng bên dưới; cần kiểm tra bằng thiết bị thứ hai. Không mở MySQL, cổng 8000 hoặc 3000 cho máy khách.

## Giao tiếp mạng và giao thức

Ứng dụng dùng **HTTPS/REST và WebSocket bảo mật (WSS), đều truyền qua TCP/TLS**. TLS và framing WebSocket do Node.js, Uvicorn và thư viện giao thức xử lý; dự án không tự định nghĩa framing TCP thô. Danh sách route hiện hành được server sinh tại `/api/docs` và `/api/openapi.json` khi server chạy.

- REST dùng prefix `/api/v1` và JSON cho đăng nhập, menu, địa chỉ, báo phí, đơn và thao tác quản trị. Health check là `/api/health`.
- WebSocket dùng `/ws` và thông điệp JSON phiên bản `v: 1`. Client xác thực qua cookie phiên và `Origin`, gửi `HELLO`; server trả `WELCOME` rồi đồng bộ bằng replay hoặc snapshot (`SYNC_BEGIN`, `SNAPSHOT_CHUNK`, `SYNC_END`).
- Sau đồng bộ, hai phía trao đổi `PING`/`PONG`, `CHAT_SEND`, `ACK`, `ERROR` và sự kiện gồm `topic`, `seq`, `eventId`, `eventType`, `payload`.
- Thứ tự được giữ trong từng topic. Client có model/cursor hợp lệ được phát lại sự kiện còn thiếu; khi cursor không còn dùng được, server gửi snapshot. Client mất đồng bộ hoặc nhận quá chậm phải đồng bộ lại hoặc kết nối lại.
- REST trả mã lỗi và thông điệp; WebSocket gửi `ERROR` hoặc đóng kết nối khi phiên, quyền, dữ liệu đầu vào hay giới hạn kết nối không hợp lệ. Retry một thao tác phải giữ nguyên khóa idempotency để tránh tạo đơn hoặc trừ kho trùng.

Luồng cập nhật realtime: client gửi yêu cầu → backend xác thực và kiểm tra nghiệp vụ → MySQL commit thay đổi cùng event/outbox → dispatcher phát sau commit → client trong topic áp dụng event theo `seq`. Khi duyệt đơn, server khóa và kiểm tra các dòng hàng trong transaction; nếu một dòng thiếu tồn thì rollback toàn bộ. Nếu đủ, server cập nhật tồn, ledger, lịch sử, idempotency và event trong cùng transaction.

## Đóng góp kỹ thuật và baseline

1. **Giao dịch tồn kho:** duyệt đơn khóa/kiểm tra toàn bộ dòng hàng, ghi tồn, ledger và trạng thái trong cùng transaction; retry dùng idempotency.
2. **Phát thay đổi:** lưu event/outbox rồi gửi WSS theo topic/seq sau commit; baseline trong phép đo là client polling định kỳ.
3. **Phục hồi:** client có thể replay các sự kiện còn thiếu hoặc nhận snapshot khi cursor không dùng được.

Đây là đóng góp tích hợp và triển khai trong phạm vi đồ án, không tuyên bố thuật toán mới.

## Luồng nghiệp vụ và dữ liệu chính

Khách đăng nhập, xem mặt hàng theo nhóm được phép, thêm món vào giỏ và gửi đơn. Server kiểm tra quyền, giá, số lượng và phí; đơn mới ở trạng thái chờ và chưa trừ tồn. Khi quản trị duyệt, server kiểm tra lại và trừ tồn trong transaction. Các bước chuẩn bị, bàn giao và giao thành công được ghi lại; khách có thể hủy đơn chờ hoặc yêu cầu hủy đơn đã duyệt theo quy tắc xử lý của hệ thống.

Quản trị tạo menu theo ngày, chọn mặt hàng, lượng, giá và nhóm được mua. Có thể mở nhiều đợt cùng giờ nếu không trùng sản phẩm đang bật trong các đợt có lịch chồng nhau. Mỗi dòng bán có tồn và giá riêng. Khi toàn bộ món đang bật hết hàng, đợt hiển thị đã bán hết; bổ sung/hoàn kho có thể cho bán tiếp nếu đợt còn thời gian và chưa đóng thủ công.

Báo cáo tính theo ngày giao thành công tại Việt Nam: doanh thu hàng, giá vốn, lãi gộp và phí giao riêng. Chế độ ngày hiển thị 7 ngày tính đến ngày được chọn; chế độ tháng hiển thị từng ngày trong tháng. Khi thiếu giá vốn của một dòng đã giao, kỳ đó hiển thị chưa đủ dữ liệu tính lãi. Nhật ký quản trị có thể lọc theo khoảng ngày và xem thay đổi trước/sau.

| Nhóm dữ liệu | Bảng tiêu biểu | Vai trò |
| --- | --- | --- |
| Tài khoản và nhóm | `users`, `customer_groups`, `sessions`, `auth_challenges` | Danh tính, quyền, phiên và xác minh |
| Sản phẩm và bán hàng | `products`, `product_images`, `daily_menus`, `offers`, `offer_prices` | Danh mục, đợt bán, giá theo nhóm và lượng còn |
| Đơn và kho | `orders`, `order_items`, `order_status_history`, `inventory_movements` | Snapshot đơn, lịch sử trạng thái và biến động kho |
| Giao hàng | `addresses`, `delivery_policies`, `pickup_slots` | Điểm nhận và chính sách tính phí |
| Realtime và quản trị | `stream_events`, `outbox`, `notifications`, `audit_logs` | Sự kiện, phát lại, thông báo và truy vết |

`db/schema.sql` là schema đầu vào của migration đầu tiên; các thay đổi sau đó nằm trong `backend/alembic/versions`. Cài mới và cập nhật schema bằng Alembic đến `head`, không chỉ import riêng schema ban đầu. MySQL/InnoDB giữ dữ liệu nghiệp vụ; ảnh tải lên nằm trong `runtime/uploads` trên máy server.

Khi cài mới, các bước hướng dẫn trên Windows và macOS đều chạy toàn bộ migration đến `head` trước khi seed (Windows dùng `setup.ps1`). Baseline 0001 còn cấu trúc yêu cầu hàng cũ vì migration 0002 cần đọc báo giá để tạo snapshot; migration 0013 gỡ các bảng `product_requests`, `request_quotes`, `request_status_history` và hai cột tham chiếu cũ trong `orders`. Do đó database mới sau khi cài hoàn tất không còn các bảng/dữ liệu yêu cầu hàng, và `seed.py` không tạo lại chúng. Không import riêng `db/schema.sql` để cài dự án.

Migration 0013 không thể rollback tự động. Hãy sao lưu database trước khi nâng cấp bản cũ; migration sẽ dừng nếu đơn hàng còn tham chiếu yêu cầu/báo giá cũ. Nếu cần lưu dữ liệu lịch sử, giữ bản sao lưu trước khi tiếp tục.

## Đồng thời và tính đúng đắn

FastAPI xử lý nhiều yêu cầu bất đồng bộ. Mỗi WebSocket có hàng đợi riêng, giới hạn kích thước để client chậm không chặn toàn bộ kết nối. Hiện ứng dụng chạy **một FastAPI worker**, vì danh sách socket đang hoạt động nằm trong bộ nhớ của tiến trình. Chạy nhiều worker cần event bus dùng chung và kiểm thử liên tiến trình.

Tính nhất quán nghiệp vụ dựa trên transaction/khóa MySQL InnoDB thay vì khóa trong bộ nhớ Python. Duyệt đơn dùng version và idempotency để chống xử lý lặp; ledger ghi biến động tồn. Luồng đồng bộ dùng `seq`, snapshot/replay và outbox để client bắt kịp sau reconnect. Đây là cách triển khai của nhóm, không tuyên bố thuật toán mới.

## Công nghệ

| Thành phần | Công nghệ |
| --- | --- |
| Giao diện | Next.js, React, TypeScript, Tailwind CSS |
| Backend và API | Python 3.12, FastAPI, SQLAlchemy asyncio, Uvicorn |
| Cơ sở dữ liệu | MySQL 8 / InnoDB, asyncmy, Alembic |
| Giao tiếp thời gian thực | WebSocket/WSS, JSON protocol v1 |
| Proxy và TLS | Node.js HTTPS proxy |
| Kiểm thử giao diện | Playwright, Microsoft Edge |
| Ảnh | Pillow và thư mục media riêng trên server |

Dependency backend được khóa trong [backend/requirements.txt](backend/requirements.txt); dependency giao diện nằm trong [frontend/package-lock.json](frontend/package-lock.json).

## Cài đặt và chạy trên Windows

### Yêu cầu

- Windows 10/11.
- Python 3.12.
- Node.js tương thích Next.js 16 (khuyến nghị Node.js 24 LTS) và npm.
- MySQL Server 8.0 trở lên đang chạy tại `127.0.0.1:3306`; tài khoản quản trị có quyền tạo database và user ứng dụng.

### Cài lần đầu

```powershell
git clone https://github.com/theycallmeheng/RealtimeOrders.git
cd RealtimeOrders
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Script cài dependency, tạo database `realtimeorders` và user riêng nếu chưa có `.env`, chạy migration đến Alembic `head`, seed dữ liệu mẫu khi database chưa có tài khoản, tạo chứng thư thử cho localhost và build giao diện. Script hỏi mật khẩu quản trị MySQL trong terminal; không thay mật khẩu root và từ chối ghi đè database đã tồn tại. Nếu đã có `.env` hoặc database cũ, kiểm tra cấu hình và sao lưu trước khi chạy setup.

### Kiểm tra trước khi cài

Mở PowerShell trong thư mục gốc dự án. Kiểm tra Python, Node.js, npm và cổng MySQL:

```powershell
python --version
node --version
npm --version
Test-NetConnection 127.0.0.1 -Port 3306
```

`TcpTestSucceeded` cần là `True`. Nếu MySQL chưa chạy, mở **Services** của Windows và khởi động dịch vụ MySQL đang cài. MySQL Workbench chỉ là công cụ quản lý, không thay thế MySQL Server. Không gửi mật khẩu root vào chat hoặc commit vào Git.

Khi script setup hỏi `MySQL administrator password`, nhập mật khẩu của tài khoản quản trị MySQL trên máy đó; ký tự mật khẩu không hiện khi gõ. Cần quyền tạo database/user. Nếu đã có `.env`, setup giữ cấu hình hiện có và chạy migration trên database mà `DATABASE_URL` đang trỏ tới; **xác định đúng database và sao lưu trước**. Nếu chưa có `.env` nhưng database `realtimeorders` đã tồn tại, bootstrap dừng để tránh ghi đè; không xóa database chỉ để chạy setup. Xem mục sao lưu và khôi phục bên dưới.

Cài lần đầu cần Internet để tải gói Python và npm. Khi hoàn tất sẽ có `.venv`, `frontend/node_modules`, `frontend/.next`, `.env` và `runtime` cục bộ. `backend/seed.py` chỉ chạy bộ dữ liệu mẫu trên database chưa có tài khoản; nếu đã có user, lần khởi động/seed sau không thêm lại sản phẩm, nhóm, giá, phí giao hoặc tài khoản, và không đổi mật khẩu hiện có. Seed được ghi giao dịch; thông tin đăng nhập demo ngẫu nhiên chỉ được lưu trong `runtime/demo-accounts.local.json` trên máy server.

#### Dữ liệu và quy tắc mẫu trong database mới

- Tạo ba nhóm khách: **Sinh viên**, **Người đi làm** và **Khách hàng thân thiết**; tạo một tài khoản quản trị mẫu và ba tài khoản khách mẫu với mật khẩu ngẫu nhiên. Xem tên đăng nhập/số điện thoại và mật khẩu ở `runtime/demo-accounts.local.json`; không chép tệp này lên Git hoặc gửi công khai.
- Nạp **56 sản phẩm** từ [`backend/seed_catalog.json`](backend/seed_catalog.json), gồm tên, SKU, danh mục, đơn vị, bước số lượng, mô tả, nhóm được phép mua và ảnh mẫu (54 URL HTTPS tại thời điểm chuẩn bị dữ liệu). URL thuộc máy chủ bên ngoài nên ảnh có thể đổi hoặc ngừng hoạt động. Đây là dữ liệu minh họa, không phải giá bán hiện hành của cửa hàng.
- Giá vốn nhập mẫu của từng sản phẩm được lưu ở `products.default_cost_price`. Giá bán mẫu chuẩn cho người đi làm bằng **150% giá vốn**, làm tròn đến đồng gần nhất; giá theo nhóm được tính từ giá chuẩn: sinh viên **giảm 5%**, khách hàng thân thiết **giảm 10%**. Quy tắc lưu tại `system_settings` với khóa `price_rules`. Ví dụ giá vốn 50.000đ → giá người đi làm 75.000đ, sinh viên 71.250đ, khách hàng thân thiết 67.500đ. Khi tạo menu, giá vốn mặc định được điền từ sản phẩm; thay đổi giá vốn trong menu sẽ tính lại giá của từng nhóm theo quy tắc đang lưu. Thay đổi dữ liệu seed không sửa lại sản phẩm/giá đã tồn tại.
- Tạo khu giao mẫu Hà Đông và chính sách giao theo quãng đường: sinh viên giao riêng **3.000đ/km trong 10km đầu**, sau đó **4.000đ/km vượt**, tối đa **15km**; người đi làm và khách hàng thân thiết **3.500đ/km trong 10km đầu**, sau đó **5.000đ/km vượt**, tối đa **15km**. Khoảng cách tính theo km thực của tuyến; phí cuối được làm tròn lên nghìn đồng gần nhất. Giao tập trung cho sinh viên miễn phí. Chính sách giao mẫu không đặt mức đơn tối thiểu.
- Đặt vị trí kho mẫu tại **96A Trần Phú, Học viện Công nghệ Bưu chính Viễn thông, Hà Đông** theo điểm đã xác nhận cho demo. Trước khi dùng một database mới ở máy khác, quản trị cần kiểm tra và xác nhận lại vị trí thực tế trong cấu hình; tọa độ mặc định không tự chứng minh kho đang ở đó.
- Không tạo menu hoặc đợt mở bán tự động. Sau đăng nhập quản trị, tạo menu ngày, chọn sản phẩm và nhập lượng hàng để mặt hàng xuất hiện cho khách. Seed tạo một điểm giao mẫu và địa chỉ giả cho ba tài khoản demo; không dùng chúng cho giao hàng thật.

Các bảng chính sau seed gồm `customer_groups`, `products`, `product_images`, `offer_prices`, `delivery_zones`, `delivery_policies` và `system_settings`. Mật khẩu tài khoản mẫu không cố định; nếu tệp đăng nhập demo bị mất sau khi seed thành công thì không chạy seed để khôi phục, vì seed cố ý không ghi đè database đang có dữ liệu.

### Khởi động server

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 start
```

### Chạy client

Mở `https://localhost:3443`. Chứng thư localhost là chứng thư thử nghiệm; trình duyệt có thể hiện cảnh báo nếu chưa tin cậy chứng thư. Tài khoản demo được sinh ngẫu nhiên, lưu tại `runtime/demo-accounts.local.json` khi seed trên database trống. Nếu database đã có tài khoản, seed không tạo lại hoặc đổi mật khẩu.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 stop-app
```

`stop-app` dừng các dịch vụ ứng dụng nhưng không dừng dịch vụ MySQL có sẵn của Windows.

### Kiểm tra dịch vụ và nhật ký

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 status
Test-NetConnection 127.0.0.1 -Port 8000
Test-NetConnection 127.0.0.1 -Port 3000
Test-NetConnection 127.0.0.1 -Port 3443
Get-Content runtime\backend-error.log -Tail 50
Get-Content runtime\frontend-error.log -Tail 50
Get-Content runtime\proxy-error.log -Tail 50
```

Trạng thái do script quản lý và cổng đang nghe giúp chẩn đoán, nhưng không tự chứng minh toàn bộ chức năng đã hoạt động. Mở `/api/health` qua đúng địa chỉ đang dùng để kiểm tra kết nối backend. Nếu cần chia sẻ log để nhờ hỗ trợ, xem và che thông tin cá nhân/bí mật trước.

Sau khi sửa source frontend, chạy `npm --prefix frontend run build`, rồi chạy `services.ps1 stop-app` và `services.ps1 start` để bản Next.js production mới được nạp. Sau thay đổi backend, cũng cần dừng/chạy lại ứng dụng. Nếu có migration mới, sao lưu trước, dừng ứng dụng rồi chạy:

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 start
```

Migration sử dụng `DATABASE_URL` trong `.env`; lệnh này thay đổi schema database được cấu hình. Đọc migration và kiểm tra bản sao lưu trước khi áp dụng cho database có dữ liệu cần giữ.

### Địa chỉ từng màn hình và điều hướng

Mỗi tab có URL riêng. Khách hàng dùng `/menu`, `/cart`, `/orders`, `/messages`, `/profile`, `/notifications`; quản trị dùng `/admin/orders`, `/admin/menus`, `/admin/products`, `/admin/messages`, `/admin/customers`, `/admin/settings`, `/admin/reports`, `/admin/audit`, `/admin/notifications`.

Có thể sao chép link, mở tab mới, tải lại và dùng nút quay lại/tiến tới của trình duyệt. URL được ưu tiên hơn tab ghi nhớ trong phiên; nếu chưa đăng nhập, ứng dụng yêu cầu đăng nhập rồi mở màn hình đã yêu cầu. Link quản trị không cấp quyền cho khách: giao diện chuyển về menu khách và backend tiếp tục kiểm tra quyền ở mọi API. Chuyển tab trong ứng dụng không khởi động lại kết nối WebSocket. Các URL được Next.js đưa về cùng ứng dụng; API `/api/*` và `/ws` giữ nguyên.

### Client ở mạng khác (demo qua Internet)

Máy của bạn chạy ứng dụng và MySQL. Cloudflare Tunnel tạo địa chỉ HTTPS công khai; bạn của bạn chỉ cần trình duyệt và Internet, không cần cài database hoặc cùng Wi-Fi:

```text
Máy khách ở mạng khác ── HTTPS / WSS ── Cloudflare Tunnel
                                            │
Máy chủ Windows: cloudflared ── proxy 127.0.0.1:3443
                                      ├─ Next.js 127.0.0.1:3000
                                      └─ FastAPI 127.0.0.1:8000 ── MySQL :3306
```

Sau khi đã hoàn thành setup trên máy server:

1. Cài Cloudflare Tunnel một lần (script tải binary Windows x64 chính thức và kiểm tra SHA-256):

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-cloudflared.ps1
   ```

2. Nhấp đúp `Start-Remote.cmd`, hoặc chạy:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 start
   ```

3. Sao chép địa chỉ `Public RealtimeOrders: https://...trycloudflare.com` được in trong cửa sổ. Cả quản trị trên máy chủ và khách ở mạng khác nên mở **cùng link này** và đăng nhập. Link là địa chỉ công khai; chỉ chia sẻ với người cần dùng trong buổi demo.
4. Mở link trên điện thoại dùng 4G/5G hoặc máy tính ở mạng khác; kiểm tra khách và quản trị thấy cập nhật khi tạo/duyệt đơn và khi kết nối lại. Server phải bật, kết nối Internet và không ngủ.

Kiểm tra link và dừng tunnel:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 stop
```

Có thể nhấp đúp `Stop-Remote.cmd` thay cho lệnh stop. Lệnh này đóng tunnel và khôi phục profile mạng trước đó; nếu trước đó dùng local, ứng dụng trở lại `https://localhost:3443`. Muốn dừng cả ứng dụng, dùng `Stop-Remote.cmd` rồi `Stop.cmd`. Không cần sao chép database, mở cổng router hoặc cài chứng thư trên máy khách; tunnel chỉ chuyển tiếp proxy ứng dụng, không chuyển tiếp cổng MySQL. Khi chế độ tunnel bật, localhost có thể chuyển hướng về hostname công khai vì hệ thống kiểm tra Origin/cookie theo hostname.

Quick Tunnel không cần tên miền/tài khoản Cloudflare, nhưng hostname thay đổi khi tạo tunnel mới, không có SLA và phụ thuộc kết nối Internet. Đây là cách demo, không phải cấu hình production. Máy khách xác minh chứng thư HTTPS công khai; tùy chọn bỏ kiểm tra chứng thư trong script chỉ áp dụng cho kết nối từ cloudflared đến proxy loopback với chứng thư tự ký.

### Tùy chọn: chạy trong cùng mạng LAN

Nếu không dùng tunnel, hai máy có thể chạy trong cùng mạng tin cậy. Trên server, lấy IPv4 LAN bằng `ipconfig`, sau đó dừng ứng dụng và chuẩn bị profile (thay IP ví dụ bằng IP thực tế):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 stop-app
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure-lan.ps1 -Address 192.168.1.25
```

Script tạo CA/leaf thử và bộ client trong `runtime/lan-client`. Trên server mở PowerShell quản trị và chạy `scripts/lan-firewall.ps1` để tạo rule TCP 3443 cho mạng Private/LocalSubnet; `-MakePrivate` chỉ dùng khi người quản lý xác định mạng đáng tin cậy vì nó thay đổi profile Windows. Khởi động lại bằng `services.ps1 start`.

Trên máy khách, cùng mạng LAN, đối chiếu fingerprint CA rồi chạy `Trust-Server.cmd` trong gói `runtime/lan-client` và mở URL HTTPS được in ra. Chỉ chuyển gói client công khai, không chuyển private key, `.env` hoặc database. Để về local: dừng ứng dụng, chạy `scripts/configure-lan.ps1 -LocalOnly`, rồi start lại. Cần nghiệm thu bằng hai thiết bị thật; hướng dẫn này không chứng minh cấu hình LAN đã được kiểm thử trên mạng hiện tại.

### Cấu hình dịch vụ ngoài

Dùng [.env.example](.env.example) làm danh sách biến; lưu giá trị cục bộ trong `.env` ở thư mục gốc. Không commit tệp này hoặc đưa bí mật vào log/chat.

- Demo: `DEMO_MODE=true`, `SMS_PROVIDER=demo`, `EMAIL_PROVIDER=demo`; mã thử được đánh dấu là demo.
- OTP Zalo: `ZALO_ACCESS_TOKEN`, `ZALO_OTP_TEMPLATE_ID`, `ZALO_OTP_CODE_FIELD`; cần OA/ZBS, quyền gửi và template được duyệt.
- SMS: `SMS_PROVIDER=twilio` cùng `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`.
- Email: `EMAIL_PROVIDER=smtp` cùng cấu hình SMTP.
- Bản đồ: không cần key; backend gọi dịch vụ công cộng OpenStreetMap/OSRM. Xác nhận tọa độ kho trong cấu hình quản trị.

Dịch vụ bản đồ công cộng không cần key hoặc billing. Photon và Nominatim chỉ gọi khi bấm tìm, có cache và giới hạn lưu lượng. Địa chỉ thiếu số nhà có thể bổ sung tại **Cấu hình → Địa chỉ công cộng đã xác nhận**; chỉ thêm điểm công cộng đã kiểm tra, không tự chia sẻ địa chỉ khách. Nominatim chỉ được gọi khi người dùng bấm tìm, tối đa một yêu cầu mỗi giây; OSRM demo cũng giới hạn lưu lượng và không bảo đảm uptime. Không nhập địa chỉ cá nhân thật/nhạy cảm hoặc dùng endpoint công cộng cho lưu lượng production.

## Cài đặt và chạy trên macOS (một máy cục bộ)

Hướng dẫn này chạy giao diện, backend, proxy TLS và MySQL trên **cùng một máy Mac**. Phần script `setup.ps1`, `services.ps1`, `remote.ps1` và các script cấu hình mạng hiện tại dành cho Windows PowerShell; không chạy các lệnh đó trong Terminal macOS. Hướng dẫn Cloudflare Tunnel ở mục Windows không phải quy trình đã kiểm thử trên Mac.

### Yêu cầu

- macOS có Terminal và Git.
- Python **3.12**, Node.js **24** và MySQL **8.4**.
- Kết nối Internet trong lần cài để tải thư viện Python/npm và dữ liệu ảnh demo.
- Homebrew là cách cài gọn nếu máy hỗ trợ các formula tương ứng. Cài Homebrew theo [hướng dẫn chính thức](https://docs.brew.sh/Installation); sau đó:

```bash
xcode-select --install  # Bỏ qua nếu Command Line Tools đã được cài.
brew install python@3.12 node@24 mysql@8.4
```

`node@24` và `mysql@8.4` là các formula phiên bản riêng của Homebrew, có thể chưa nằm trong `PATH`. Thêm đường dẫn một lần vào `~/.zprofile`, rồi mở Terminal mới hoặc nạp cấu hình:

```bash
echo 'export PATH="$(brew --prefix node@24)/bin:$(brew --prefix mysql@8.4)/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Kiểm tra phiên bản:

```bash
python3.12 --version
node --version
npm --version
mysql --version
```

Các formula này hiện thuận tiện nhất trên Apple Silicon. Nếu Mac Intel không có bottle Homebrew phù hợp, cài Python 3.12 từ [python.org](https://www.python.org/downloads/macos/), Node 24 từ [nodejs.org](https://nodejs.org/en/download) và MySQL Community Server 8.4 từ [trang tải MySQL](https://dev.mysql.com/downloads/mysql/), chọn đúng kiến trúc máy. Tiếp tục từ bước kiểm tra phiên bản bên trên. Không cài thêm MySQL nếu máy đã có một server khác đang dùng cổng 3306; trước tiên hãy xác định database và sao lưu dữ liệu cần giữ.

### Cài lần đầu

Clone repo, vào thư mục dự án và tạo file cấu hình riêng:

```bash
git clone https://github.com/theycallmeheng/RealtimeOrders.git
cd RealtimeOrders
cp .env.example .env
nano .env
```

Trong `.env`, sửa tối thiểu các giá trị sau:

```dotenv
DATABASE_URL=mysql+asyncmy://realtimeorders_app:THAY_BANG_MAT_KHAU@127.0.0.1:3306/realtimeorders?charset=utf8mb4
APP_SECRET=THAY_BANG_CHUOI_BI_MAT_RIENG
APP_ORIGIN=https://localhost:3443
COOKIE_SECURE=true
DEMO_MODE=true
SMS_PROVIDER=demo
EMAIL_PROVIDER=demo
```

Tạo chuỗi bí mật rồi dán kết quả vào `APP_SECRET`:

```bash
python3.12 -c 'import secrets; print(secrets.token_hex(32))'
```

Dùng mật khẩu MySQL riêng cho ứng dụng, chỉ chứa ký tự chữ và số để tránh phải mã hóa ký tự đặc biệt trong URL. Không dùng mật khẩu root trong `DATABASE_URL`; không commit `.env`.

### Tạo database và tài khoản ứng dụng

Khởi động MySQL và mở client quản trị:

```bash
brew services start mysql@8.4
mysql -u root
```

Homebrew thường cài MySQL cục bộ với tài khoản `root` chưa đặt mật khẩu ban đầu. Nếu máy đã đặt mật khẩu root, dùng `mysql -u root -p` và nhập mật khẩu tại Terminal. Tại dấu nhắc MySQL, chạy lệnh sau; thay `MAT_KHAU_RIENG` bằng mật khẩu chữ-số do bạn chọn. Nếu database đã tồn tại, **không chạy lại lệnh tạo hoặc xóa database**; hãy kiểm tra `.env` và sao lưu trước:

```sql
CREATE DATABASE realtimeorders CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'realtimeorders_app'@'127.0.0.1' IDENTIFIED BY 'MAT_KHAU_RIENG';
GRANT ALL PRIVILEGES ON realtimeorders.* TO 'realtimeorders_app'@'127.0.0.1';
FLUSH PRIVILEGES;
EXIT;
```

Đảm bảo mật khẩu trong câu `CREATE USER` giống mật khẩu ở `DATABASE_URL`. Cấu hình phải trỏ đến `127.0.0.1:3306`, vì user ứng dụng được tạo cho host này.

### Cài thư viện, migration và dữ liệu mẫu

Chạy từ thư mục gốc `RealtimeOrders`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
mkdir -p runtime
cd backend
python -m alembic upgrade head
python seed.py
cd ..
python scripts/create_cert.py
cd frontend
npm ci
npm run build
cd ..
```

Dependency `winloop` chỉ được cài trên Windows; pip tự bỏ qua trên macOS. `seed.py` chỉ tạo tài khoản và dữ liệu mẫu khi database chưa có người dùng. Tài khoản/mật khẩu demo được ghi trong `runtime/demo-accounts.local.json` trên máy này; không chia sẻ công khai.

### Khởi động và dừng ứng dụng

Mở ba cửa sổ Terminal, mỗi cửa sổ chạy một thành phần. Thay `/duong/dan/RealtimeOrders` bằng đường dẫn clone thực tế của bạn.

**Cửa sổ 1 — backend:**

```bash
cd /duong/dan/RealtimeOrders/backend
source ../.venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Cửa sổ 2 — giao diện:**

```bash
cd /duong/dan/RealtimeOrders/frontend
npm run start
```

**Cửa sổ 3 — HTTPS proxy:**

```bash
cd /duong/dan/RealtimeOrders
node scripts/proxy.mjs
```

Mở `https://localhost:3443`. Chứng thư do `create_cert.py` tạo là chứng thư tự ký dành cho phát triển; trình duyệt có thể cảnh báo. Chỉ tiếp tục khi địa chỉ đúng là localhost, không dùng chứng thư này cho tên miền công khai. Kiểm tra backend và database bằng `https://localhost:3443/api/health`; trạng thái bình thường trả JSON có `"status":"ok"`.

Dừng từng tiến trình bằng `Ctrl+C` trong cửa sổ Terminal tương ứng. MySQL có thể để chạy cho lần sau; nếu muốn dừng dịch vụ:

```bash
brew services stop mysql@8.4
```

### Lỗi thường gặp trên macOS

| Hiện tượng | Cách xử lý |
| --- | --- |
| `command not found: node`, `npm` hoặc `mysql` | Nạp lại `~/.zprofile`, kiểm tra `brew --prefix node@24` và `brew --prefix mysql@8.4`, rồi mở Terminal mới. Nếu cài bằng trình cài đặt chính thức, kiểm tra lại `PATH`. |
| Không khởi động được MySQL hoặc cổng 3306 đang dùng | Kiểm tra `brew services list` và `lsof -nP -iTCP:3306 -sTCP:LISTEN`. Chỉ dừng đúng server mà bạn định dùng; không xóa datadir MySQL để giải quyết xung đột. |
| `Access denied` hoặc backend không kết nối database | Kiểm tra `DATABASE_URL`, mật khẩu, user có host `127.0.0.1`, database `realtimeorders` và MySQL đang nghe cổng 3306. Thử `mysql -h 127.0.0.1 -u realtimeorders_app -p realtimeorders`. |
| `ModuleNotFoundError: app` khi chạy backend | Chuyển vào thư mục `backend`, kích hoạt `.venv` ở thư mục gốc rồi chạy lại lệnh Uvicorn ở trên. |
| Trang báo 502 hoặc chưa sẵn sàng | Kiểm tra cả ba Terminal; backend dùng cổng 8000, Next.js dùng 3000, proxy dùng 3443. Dùng `lsof -nP -iTCP:8000 -sTCP:LISTEN` (đổi cổng để kiểm tra từng dịch vụ). |
| Trình duyệt cảnh báo chứng thư | Đây là chứng thư tự ký cho localhost. Xác nhận URL là `https://localhost:3443`; không bỏ qua cảnh báo nếu mở bằng hostname/IP khác. |
| `npm ci` báo phiên bản Node không tương thích | Chọn Node 24, mở Terminal mới sau khi sửa `PATH`, rồi xác nhận `node --version` trước khi chạy lại `npm ci`. |

Đây là hướng dẫn chạy cục bộ; chưa được nghiệm thu trên máy Mac. Muốn cho thiết bị ở mạng khác truy cập từ máy Mac, cần một quy trình tunnel/chứng thư phù hợp riêng; các script Windows trong repo không chạy trực tiếp trên macOS.

## Kiểm thử và thực nghiệm

Test nghiệp vụ cần database MySQL audit riêng; không chạy trên database có dữ liệu thật. Các nhóm cần kiểm tra gồm phân quyền, tính tồn khi đồng thời, retry idempotent, khôi phục WebSocket, báo cáo và trải nghiệm trên điện thoại.

Quy trình cô lập mẫu trên Windows: cần MySQL server cục bộ, `mysqldump.exe`/`mysql.exe` tại `C:\Program Files\MySQL\MySQL Server 8.0\bin` và mật khẩu root trong tệp cục bộ `runtime/mysql-3306-admin-password.local` (tên tệp theo cổng thực tế). Tệp này nằm trong `runtime` bị Git bỏ qua; không chia sẻ mật khẩu. `prepare` sao lưu nguồn, tạo một database và user audit mới, sao chép ảnh rồi chạy dịch vụ trên bản sao; các database audit **được giữ lại**, không tự xóa. Trước khi bắt đầu, dừng tunnel (nếu bật) bằng `Stop-Remote.cmd` và dừng ứng dụng bằng `services.ps1 stop-app` để giải phóng các cổng. Sau đó:

```powershell
.\.venv\Scripts\python.exe scripts\isolated_validation.py prepare
.\.venv\Scripts\python.exe scripts\isolated_validation.py backend
.\.venv\Scripts\python.exe scripts\isolated_validation.py browser
.\.venv\Scripts\python.exe scripts\isolated_validation.py finish
```

`backend` chạy pytest trên database audit; `browser` chạy Playwright với Microsoft Edge. `finish` dừng bản thử, kiểm tra fingerprint database nguồn và chạy lại ứng dụng cấu hình bình thường; nếu cần tunnel, khởi động lại bằng `Start-Remote.cmd`. Không coi bản copy kiểm thử là bản backup duy nhất. Kiểm tra type và build giao diện:

```powershell
npm --prefix frontend run check
npm --prefix frontend run build
```

Một lệnh đo tải mẫu trong môi trường audit:

```powershell
.\.venv\Scripts\python.exe scripts\isolated_validation.py run -- "{python}" scripts\load_test.py --clients 100 --seconds 30 --rps 10 --reconnect-fraction 0.1
```

Đầu ra lần chạy mới được ghi cục bộ trong `evidence/` và không nằm trong gói source. Khi báo cáo, ghi commit, cấu hình máy, cách tạo tải, số lần lặp và phạm vi phép đo; không dùng số kết nối mô phỏng để khẳng định số người mua đồng thời.

## Lỗi thường gặp

| Hiện tượng | Cách kiểm tra và xử lý |
| --- | --- |
| `python`, `node` hoặc `npm` không được nhận diện | Cài đúng phiên bản yêu cầu, mở lại PowerShell và kiểm tra `--version`. Nếu có nhiều bản Python, bảo đảm `python` trỏ tới 3.12 trước khi tạo `.venv`. |
| Không kết nối MySQL cổng 3306 | Kiểm tra `Test-NetConnection`, dịch vụ MySQL, host/port và thông tin kết nối trong `.env`; kiểm tra quyền user ứng dụng. Không đổi mật khẩu root hoặc xóa database để xử lý lỗi. |
| `Target database already exists` | Bootstrap cố ý dừng. Kiểm tra database hiện có, `.env` và bản sao lưu; dùng cấu hình phù hợp hoặc quy trình chuyển database trong tài liệu vận hành. |
| `Migration failed` hoặc backend báo thiếu bảng/cột | Xem lỗi migration và xác nhận đúng `DATABASE_URL`; sao lưu, kiểm tra phiên bản migration rồi thực hiện `alembic upgrade head`. Tránh chạy migration trên database chưa xác định. |
| Cổng 3000, 8000 hoặc 3443 đã được sử dụng | Kiểm tra `Get-NetTCPConnection -State Listen -LocalPort 3000,8000,3443` và `services.ps1 status`. Chỉ dừng tiến trình thuộc dự án bằng `stop-app`; xác định tiến trình khác trước khi xử lý. |
| `Network profile changed` | Chạy `services.ps1 stop-app`, sau đó `services.ps1 start` với profile hiện hành. Nếu muốn dừng tunnel, dùng `Stop-Remote.cmd` trước. |
| Trình duyệt báo chứng thư localhost không tin cậy | Chứng thư localhost là chứng thư thử. Xác nhận đúng `https://localhost:3443`; cách tin cậy CA cho LAN nằm ở mục chạy trong cùng mạng. Link Cloudflare dùng chứng thư công khai và không cần cài CA localhost trên client. |
| Trang báo 502 hoặc đang khởi động | Kiểm tra trạng thái backend, frontend, proxy, cổng tương ứng và log lỗi trong `runtime`; xác nhận MySQL đang chạy, rồi thử lại sau khi dịch vụ sẵn sàng. |
| Không thấy giao diện mới | Build lại frontend, dừng/chạy lại dịch vụ rồi tải lại bằng **Ctrl+F5**. Khi đang dùng tunnel, mở đúng link tunnel thay vì `localhost`. |
| Link Cloudflare không hoạt động hoặc đổi link | Kiểm tra `scripts/remote.ps1 status` và `runtime/tunnel-error.log`; chạy `Start-Remote.cmd` và dùng link vừa in. Máy server cần bật, không ngủ và có Internet; Quick Tunnel cấp link mới khi khởi tạo lại. |
| Màn hình hiển thị đang kết nối lại | Kiểm tra mạng, `/api/health`, tunnel/proxy và backend. Client tự kết nối lại, nhưng đợi đồng bộ xong trước khi gửi thao tác. |
| Menu trống hoặc nút mua bị khóa | Kiểm tra đợt đã mở trong đúng thời gian, nhóm khách được phép, giá và tồn. Đơn chờ chưa giữ hàng; tồn bị trừ khi duyệt. |
| Không tìm được địa chỉ hoặc không tính được tuyến | Kiểm tra Internet của server, vị trí kho và điểm giao đã xác nhận; dịch vụ bản đồ công cộng có giới hạn và dữ liệu số nhà có thể thiếu. Thử tìm điểm gần đó rồi chọn vị trí trên bản đồ. |
| Không nhận được OTP thật | Cấu hình mẫu là demo. Gửi Zalo/SMS thật cần nhà cung cấp và thông tin hợp lệ; kiểm tra chế độ cùng cấu hình tương ứng trong `.env`, không công khai token. |

## Thư mục cục bộ và dữ liệu

`backend`, `frontend`, `db/schema.sql` và `scripts` cần cho mã nguồn/cài đặt. `.venv`, `frontend/node_modules` và `frontend/.next` là môi trường/gói build có thể tạo lại, nhưng xóa chúng sẽ phải cài/build lại. `dist` là gói xuất có thể tạo lại; `evidence` chứa kết quả đo và có thể cần cho báo cáo.

`runtime` chứa cả tệp có thể tạo lại **và dữ liệu quan trọng** như ảnh tải lên, tài khoản demo, cấu hình/chứng thư, log và bản sao lưu. Không xóa cả thư mục khi chưa kiểm tra. `.env` chứa cấu hình và bí mật kết nối; không đưa lên Git. Nếu có datadir MySQL cũ, nên giữ bản dự phòng ở ngoài project; kiểm tra datadir đang dùng và sao lưu trước khi quyết định xử lý. Lệnh backup SQL dùng `.venv\Scripts\python.exe scripts\backup.py`; sao lưu thêm `runtime/uploads` riêng để giữ ảnh. Chỉ khôi phục vào database mới, kiểm tra dữ liệu và ảnh trước khi chuyển cấu hình; không import đè database đang dùng.

### Sao lưu và kiểm tra khôi phục

Lệnh `scripts/backup.py` tạo SQL dump bằng `mysqldump` của MySQL hiện cấu hình; tệp mặc định là `runtime/backups/realtimeorders.sql`. Bản dump có dữ liệu khách nên phải giữ riêng, không commit. Sao lưu thêm toàn bộ `runtime/uploads` và bảo quản `.env`/thông tin kết nối theo cách phù hợp.

Chỉ thử khôi phục vào một database mới, đối chiếu bảng, đơn và ảnh trước khi chuyển cấu hình; không import đè database đang hoạt động. `scripts/restore_check.py` là công cụ kiểm tra trên database mới và cần thông tin quản trị MySQL trong tệp cục bộ tương ứng; kiểm tra đường dẫn, quyền và bản dump trước khi chạy. Công cụ để lại database thử để kiểm tra, không tự xóa.

## Kịch bản demo

1. Quản trị tạo hoặc mở menu hôm nay, cấu hình sản phẩm, giá, lượng và nhóm được mua.
2. Khách dùng tài khoản demo, chọn mặt hàng, thêm vào giỏ và gửi đơn.
3. Quản trị duyệt; kiểm tra tồn chỉ giảm sau khi duyệt và hai màn hình nhận cập nhật.
4. Thử chat/thông báo; ngắt rồi nối lại client để quan sát đồng bộ.
5. Nếu trình bày client ở mạng khác, mở cùng link tunnel trên điện thoại 4G/5G và kiểm tra đồng bộ.

## Giới hạn và hướng phát triển

- Một server ứng dụng và một worker; hub WebSocket không chia sẻ trạng thái giữa nhiều tiến trình.
- Cấu hình mặc định dùng localhost; LAN cần chứng thư và firewall phù hợp. Cloudflare Quick Tunnel phục vụ demo qua Internet, không có cam kết uptime và cần máy chủ tiếp tục chạy.
- Gửi OTP Zalo/SMS/email phụ thuộc dịch vụ bên ngoài. Tra cứu địa chỉ và tuyến đường dùng dịch vụ công cộng OSM/OSRM, chịu giới hạn và có thể gián đoạn.
- Chưa có thanh toán trực tuyến, tích hợp đơn vị vận chuyển hoặc đổi trả sau khi giao thành công.
- Cần đo lại workload có đặt/duyệt đơn, thử mạng chậm và phục hồi lỗi trên revision bàn giao; kết quả mô phỏng chỉ áp dụng cho cấu hình đã mô tả.

## Cấu trúc repository

```text
backend/       FastAPI, nghiệp vụ, migration và kiểm thử backend
frontend/      giao diện Next.js và kiểm thử trình duyệt
db/            schema đầu vào cho migration đầu tiên
scripts/       setup, chạy/dừng, kiểm thử cô lập, đo tải, backup/restore
runtime/       cấu hình, tài khoản demo, log và dữ liệu cục bộ; không commit
evidence/      kết quả kiểm thử/đo cục bộ; không commit
```

## Nguồn tham khảo

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) · [MDN WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)
- [MySQL InnoDB locking reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html) · [Next.js self-hosting](https://nextjs.org/docs/app/guides/self-hosting)
- [Cài Homebrew](https://docs.brew.sh/Installation) · [Python 3.12 trên Homebrew](https://formulae.brew.sh/formula/python@3.12) · [Python cho macOS](https://www.python.org/downloads/macos/) · [Node.js 24 trên Homebrew](https://formulae.brew.sh/formula/node@24) · [Node.js downloads](https://nodejs.org/en/download)
- [MySQL 8.4 trên Homebrew](https://formulae.brew.sh/formula/mysql@8.4) · [MySQL cho macOS](https://dev.mysql.com/doc/refman/8.4/en/macos-installation.html) · [MySQL Community downloads](https://dev.mysql.com/downloads/mysql/) · [Yêu cầu Node.js của Next.js](https://nextjs.org/docs/pages/getting-started/installation)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [Chính sách Nominatim](https://operations.osmfoundation.org/policies/nominatim/) · [OSRM demo](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
