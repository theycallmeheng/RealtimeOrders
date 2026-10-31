# Truy cập từ mạng khác qua Cloudflare Tunnel

Máy chủ Windows chạy MySQL, FastAPI, Next.js và proxy như hiện tại. Máy khách chỉ cần trình duyệt và Internet, không cần cùng Wi-Fi, cài Python/MySQL hoặc nhập IP LAN.

```text
Trình duyệt khách/quản trị ở mạng bất kỳ
    → HTTPS/WSS tại https://<tên-ngẫu-nhiên>.trycloudflare.com
    → Cloudflare → cloudflared trên máy chủ
    → HTTPS 127.0.0.1:3443
        ├─ Next.js 127.0.0.1:3000
        └─ FastAPI 127.0.0.1:8000 → MySQL trên máy chủ
```

Tunnel chỉ chuyển tiếp ứng dụng qua proxy 3443. Script không mở cổng router, đổi profile Wi-Fi, thêm firewall rule hoặc chuyển tiếp MySQL 3306. Backend, frontend và proxy của profile `remote` chỉ nghe loopback; cấu hình dịch vụ MySQL có sẵn không bị thay đổi.

## Chuẩn bị một lần trên máy chủ

1. Cài và chạy ứng dụng theo README, bảo đảm localhost hoạt động.
2. Tại thư mục gốc dự án, cài bản cloudflared Windows x64 đã khóa phiên bản và kiểm tra SHA-256:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-cloudflared.ps1
```

Binary được tải từ release chính thức về `runtime/tools/cloudflared.exe`, không đưa vào Git. Script này dành cho Windows x64. Cần Internet để tải và để sử dụng tunnel.

## Bật và chia sẻ link

Nhấp đúp **Start-Remote.cmd**, hoặc chạy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 start
```

Script dừng ba dịch vụ ứng dụng, tạo Quick Tunnel, lấy hostname HTTPS, lưu profile mạng rồi khởi động lại ứng dụng với đúng `APP_ORIGIN`. Database và dữ liệu giữ nguyên. Script lưu profile trước đó để khôi phục khi tắt tunnel; gọi start lần nữa khi tunnel đang chạy dùng lại link hiện tại.

Chia sẻ link `Public RealtimeOrders: https://...trycloudflare.com` được in ra. Mọi client, kể cả quản trị trên máy chủ, nên dùng **cùng link này**; đăng nhập lại vì cookie của localhost không dùng chung với hostname mới. Không gửi tệp tài khoản cục bộ cho người ngoài. Khi profile remote đang bật, mở trang localhost sẽ được chuyển sang link công khai.

Máy chủ phải bật, kết nối Internet và không ngủ. Quick Tunnel không cần tài khoản Cloudflare hay tên miền, nhưng link thay đổi khi tạo tunnel mới và không có cam kết uptime. Đây là cấu hình demo; muốn URL cố định cần named tunnel và tên miền phù hợp.

## Trạng thái và tắt

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote.ps1 stop
```

**Stop-Remote.cmd** thực hiện lệnh stop: dừng connector do project tạo, khôi phục profile mạng trước đó và chạy lại ứng dụng. Nếu trước đó là local, quay về `https://localhost:3443`. Muốn đóng toàn bộ ứng dụng, chạy Stop-Remote.cmd trước, sau đó Stop.cmd. `services.ps1 stop-app` chỉ dừng ứng dụng, không dừng connector; dùng cách này chỉ khi cần khởi động lại dịch vụ trong cùng phiên tunnel.

State và log nằm trong `runtime/tunnel.local.json`, `runtime/network.local.json`, `runtime/tunnel.log`, `runtime/tunnel-error.log`. Các tệp đều bị Git bỏ qua. Không chỉnh state khi dịch vụ đang chạy. Nếu tunnel bị dừng ngoài script hoặc máy vừa khởi động lại, chạy Start-Remote.cmd để cấp link mới.

## Kiểm tra

- Trên điện thoại tắt Wi-Fi, dùng 4G/5G mở link công khai và đăng nhập.
- Trên máy chủ mở cùng link bằng tài khoản quản trị; kiểm tra hai phía nhận cập nhật và client đồng bộ lại sau mất mạng.
- Kiểm tra kết nối HTTPS/WSS có xác minh chứng thư, đăng nhập và phục hồi snapshot bằng công cụ chỉ đọc (ngoài tạo/thu hồi phiên đăng nhập):

```powershell
.\.venv\Scripts\python.exe scripts\remote_probe.py
```

Công cụ lấy tài khoản demo từ tệp cục bộ, không in mật khẩu/cookie/token, không tạo sản phẩm, đơn hoặc tin nhắn. Kết quả ghi vào `runtime/browser-test-results/remote-acceptance.json`; đây là phép kiểm tra đi qua Internet từ máy chủ, không thay thế kiểm thử bằng thiết bị ở mạng khác.

## TLS, phiên đăng nhập và giới hạn

Khách nhận chứng thư HTTPS công khai của Cloudflare và dùng WSS trên cùng hostname. `--no-tls-verify` chỉ áp dụng cho đoạn connector → proxy HTTPS loopback có chứng thư tự ký; client không tắt kiểm tra chứng thư. Backend tiếp tục kiểm tra Origin, cookie phiên và CSRF. Proxy nhận địa chỉ client do Cloudflare truyền qua connector cục bộ để các giới hạn theo IP tiếp tục hoạt động.

Quick Tunnel có giới hạn 200 yêu cầu đang xử lý, không có SLA và không hỗ trợ SSE; ứng dụng này dùng WebSocket. Khi đường truyền hoặc Cloudflare ngắt WSS, client dùng cơ chế reconnect/snapshot/replay hiện có. Môi trường demo/OTP và tài khoản vẫn theo cấu hình hiện hành; bật tunnel không tự chuyển sang cấu hình vận hành thương mại.

Nếu thấy 502, kiểm tra ba dịch vụ ứng dụng và log của chúng; nếu hostname cũ không truy cập được, xem URL hiện tại bằng lệnh status. Nếu start thất bại sau khi tạo connector, script cố gắng dừng connector và khôi phục profile trước đó.

Nguồn: [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [WebSockets](https://developers.cloudflare.com/network/websockets/), [cloudflared releases](https://github.com/cloudflare/cloudflared/releases).
