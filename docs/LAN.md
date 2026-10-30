# Chạy RealtimeOrders trên hai máy trong LAN

Máy server chạy MySQL, FastAPI, Next.js và proxy HTTPS. Máy client chỉ cần trình
duyệt. Mọi tài khoản đọc và ghi cùng database trên server; WSS truyền sự kiện sau
commit. Máy client không cài MySQL và không sao chép database.

## 1. Chuẩn bị máy server

Cài project theo README trước. Hai máy cần truy cập được nhau trong cùng Wi-Fi/LAN.
Lấy IPv4 của máy server bằng ipconfig; dùng địa chỉ riêng của Wi-Fi/Ethernet,
không dùng địa chỉ của VPN hoặc card mạng ảo.

Tại thư mục project, thay địa chỉ ví dụ bằng IPv4 của server:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 stop-app
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure-lan.ps1 -Address 192.168.1.25

Có thể bỏ tham số Address nếu máy chỉ có một card mạng đang có default gateway.
Script tạo runtime/network.local.json, bộ TLS trong runtime/tls-lan và thư mục
runtime/lan-client. Các tệp này nằm ngoài Git. Cấu hình LAN không chép IP, mật khẩu
hay private key vào source. CA được giữ khi đổi IP để client không phải tin cậy
lại một CA mới; leaf certificate chứa IP hiện tại và có hạn 90 ngày.

Khi start, services.ps1 đặt APP_ORIGIN theo network.local.json. Frontend và FastAPI
vẫn nghe 127.0.0.1 ở cổng 3000/8000. Proxy nghe loopback và đúng IP LAN đã chọn ở
cổng 3443. Truy cập trang qua localhost sẽ chuyển đến URL LAN đang cấu hình.
Người bán và khách phải dùng cùng URL LAN để Origin/cookie/WSS nhất quán.

## 2. Firewall trên server

Mở PowerShell bằng Run as administrator rồi chạy:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\lan-firewall.ps1

Nếu mạng đang Public và đây là Wi-Fi/LAN tin cậy để demo, dùng thêm MakePrivate:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\lan-firewall.ps1 -MakePrivate

MakePrivate đổi profile của đúng card mạng mang IP đã chọn; việc này cũng áp dụng
các rule Private khác đang có trên máy. Rule của project chỉ cho phép TCP 3443,
chương trình node.exe, IP/card mạng đã chọn, profile Private và máy trong LocalSubnet.
Script không mở cổng MySQL/8000/3000 và không tắt Windows Firewall.
MySQL vẫn là dịch vụ sẵn có; tài khoản ứng dụng kết nối qua loopback.

Kết quả cấu hình firewall nằm ở runtime/lan-firewall.local.json.

## 3. Khởi động và chuyển bộ client

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 start

Dùng URL được in ra, ví dụ https://192.168.1.25:3443.
Chuyển toàn bộ thư mục runtime/lan-client cho bạn cùng nhóm qua kênh phù hợp.
Thư mục này chỉ có chứng thư CA công khai, fingerprint và lệnh kết nối; không có
private key, database, session token hoặc mật khẩu.

Trên Windows của máy client:

1. Kết nối cùng Wi-Fi/LAN và đối chiếu SHA256 chứng thư với người giữ server.
2. Chạy Trust-Server.cmd một lần. Script chỉ tin cậy chứng thư trong CurrentUser
   Root, kiểm tra fingerprint trước khi import và không yêu cầu quyền quản trị.
3. Chạy Open-RealtimeOrders.cmd hoặc nhập URL server vào Edge/Chrome.
4. Đăng nhập bằng tài khoản được người giữ server cung cấp riêng.

Máy server cũng dùng bộ này nếu muốn trình duyệt của mình tin cậy CA demo.
Start/configure không tự cài chứng thư vào trust store. Firefox có thể dùng kho
CA riêng; khi đó import CA công khai vào mục Authorities của Firefox hoặc dùng
Edge/Chrome. Không chuyển runtime/tls-lan hoặc file .env sang máy client.

## 4. Kịch bản nghiệm thu hai máy

Máy server đăng nhập quản trị; máy client đăng nhập khách. Khách đặt một đơn,
quản trị duyệt, hai màn hình nhận đúng trạng thái và tồn kho. Gửi chat hai chiều.
Ngắt Wi-Fi máy client, tạo thay đổi ở server, nối lại rồi xác nhận dữ liệu phục hồi.
Chụp ảnh hai màn hình và lưu thời điểm, IP, kết quả thực; không gọi test trên cùng
một máy là đã nghiệm thu hai máy vật lý.

Health URL: https://IP-SERVER:3443/api/health.
Trên máy client có thể kiểm tra cổng bằng:

    Test-NetConnection 192.168.1.25 -Port 3443

Nếu timeout, kiểm tra server còn chạy, IP còn đúng, profile/rule firewall và tùy chọn
client isolation của hotspot/router. Nếu lỗi chứng thư, kiểm tra IP trùng SAN và
đã import đúng CA. Nếu đăng nhập/WSS bị từ chối, dùng đúng URL được cấu hình thay
vì trộn localhost, hostname hoặc IP khác.

## 5. Khi IP thay đổi hoặc muốn quay lại localhost

Đổi IP: dừng app, chạy configure-lan.ps1 với IP mới, chạy lại lan-firewall.ps1 để
cập nhật địa chỉ rule, rồi start. Gửi lại thư mục lan-client để cập nhật URL.
CA cũ được giữ; không cần import lại nếu fingerprint không đổi.

Quay lại localhost:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 stop-app
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure-lan.ps1 -LocalOnly
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 start

Xóa riêng rule project từ PowerShell quản trị:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\lan-firewall.ps1 -Remove

Gỡ CA đã import bằng Trust-Server.ps1 -Remove trong thư mục client.
Việc gỡ rule không tự đổi profile Wi-Fi của Windows.

## 6. Kiểm thử tự động

Unit cho SAN/chuỗi chứng thư, CA ổn định, gói client không có key và cấu hình bind:

    .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -p "test_*.py"
    node --test scripts/tests/network_config.test.mjs

Quy trình isolated_validation mặc định dùng loopback để bộ integration không phụ
thuộc Wi-Fi. Sau khi tạo bản audit và chạy backend suite, có thể đổi cùng instance
audit sang cấu hình LAN, chạy probe TLS/WSS và browser suite:

    .\.venv\Scripts\python.exe scripts\isolated_validation.py --network-mode configured restart
    .\.venv\Scripts\python.exe scripts\isolated_validation.py run -- "{python}" scripts\lan_probe.py
    .\.venv\Scripts\python.exe scripts\isolated_validation.py browser
    .\.venv\Scripts\python.exe scripts\isolated_validation.py finish

Probe chỉ cho phép database audit, xác minh CA/SAN thật, kiểm tra hai kết nối WSS,
chat live, retry không tạo trùng, reconnect/replay và từ chối Origin sai.
Browser suite dùng APP_ORIGIN của instance audit; cấu hình Playwright hiện bỏ qua
lỗi trust hệ điều hành, còn probe Python xác minh chứng thư bằng CA được xuất.
Kết quả ghi rõ cùng máy hay hai máy. Finish kiểm tra database nguồn rồi khởi động
lại ứng dụng thường theo cấu hình LAN hiện tại.

Các bước trên là quy trình để nhóm tự nghiệm thu với cấu hình mạng và thiết bị đang dùng.
