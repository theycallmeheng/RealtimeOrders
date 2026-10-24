# Cài đặt và vận hành RealtimeOrders

## Một máy Windows

README mô tả setup/start/stop. `runtime/services.local.json` chỉ chứa PID, thời
điểm tạo và dấu hiệu lệnh; script dừng chỉ những tiến trình còn khớp cả ba điều kiện.
Không dừng dịch vụ MySQL của người dùng. Từ 23/10, bản cài mặc định dùng MySQL
sẵn có ở `127.0.0.1:3306`, database `realtimeorders`, user riêng giới hạn quyền
trên database này. Mật khẩu quản trị dùng để tạo/chuyển DB nằm cục bộ tại
`runtime/mysql-3306-admin-password.local`, không đưa lên Git/Drive.

`runtime/mysql.local.json` có `managed: false`, host 127.0.0.1 và port 3306;
Start/Stop chỉ quản lý ba tiến trình ứng dụng. Dịch vụ Windows `MySQL80` tự quản
lý datadir của nó. Instance cũ 3307 đã dừng; datadir cũ
`D:\Dev PTIT\RealtimeOrders-data\mysql-data` và `runtime/mysql-data` được giữ
để dự phòng. Không chạy đồng thời các bản sao cùng một datadir. Backup mới phải
lấy từ `DATABASE_URL` đang dùng và ảnh trong runtime/uploads của bản bàn giao.

`scripts/migrate_mysql.py` chỉ nhận database đích chưa tồn tại, sao lưu cấu hình
và SQL trong runtime/backups, dừng tiến trình ghi trong lúc chuyển, đối chiếu số
dòng/hash mọi bảng trước khi đổi kết nối. Nếu chưa hoàn tất, khôi phục cấu hình
nguồn và khởi động lại ứng dụng; không drop DB đích hoặc DB nguồn. Bằng chứng
của lần chuyển thành công nằm tại `evidence/mysql-port-migration.json`.

`seed.py` chỉ seed database chưa có user; không reset, thay mật khẩu hoặc ghi đè
tài khoản hiện có. Mật khẩu demo được sinh ngẫu nhiên, chỉ lưu cục bộ trong tệp
ignored. Nếu thất lạc, dùng chức năng khôi phục OTP hoặc quản trị DB theo quy trình
của người quản lý; không sửa code để có mật khẩu chung.

## Cấu hình thật

`DATABASE_URL` trỏ DB riêng; `APP_SECRET` sinh ngẫu nhiên tối thiểu 32 ký tự.
`APP_ORIGIN` phải trùng chính xác scheme/host/port của giao diện.
Cookie có HttpOnly, Secure và SameSite Strict; API ghi dùng Origin và CSRF.
WSS dùng cookie + Origin, không đưa token trong URL hay localStorage.

Muốn gửi SMS: `SMS_PROVIDER=twilio`, điền SID/token/sender được cấp; thử trước
trên số được phép, đối chiếu log nhà cung cấp. Email: `EMAIL_PROVIDER=smtp`, điền
SMTP host/port/user/password/from; kết nối SMTP dùng STARTTLS. `DEMO_MODE=false`
không chấp nhận SMS demo và không trả mã trong API. Adapter có mã triển khai;
SMS/email thực tế chưa được nghiệm thu khi chưa có tài khoản dịch vụ.

## LAN và tên miền

Proxy thử hiện nghe `127.0.0.1:3443`. Để demo hai máy, chọn địa chỉ server ổn định,
đổi địa chỉ nghe proxy sang LAN (hoặc `0.0.0.0`), đặt APP_ORIGIN tương ứng và dùng
chứng thư có SAN cho host đó, được máy khách tin cậy. Chỉ mở cổng proxy trong
firewall của môi trường được phép; không mở MySQL/8000/3000 cho khách.
Không tự cài chứng thư vào trust store hay sửa firewall trong các script này.

Triển khai công khai cần reverse proxy được vận hành đầy đủ, chứng thư CA hợp lệ,
backup ngoài máy, giới hạn body/rate tại biên, giám sát, quản lý secrets và domain
được sở hữu. Node proxy trong source phục vụ cục bộ/bài tập; chưa là cấu hình
triển khai công khai được kiểm định. Hiện chỉ một FastAPI worker; cần shared bus
đã kiểm thử trước khi chạy nhiều process/host.

## Backup và khôi phục

`scripts/backup.py` gọi mysqldump `--single-transaction --hex-blob` và truyền mật
khẩu bằng môi trường subprocess, không in hoặc đặt trong tham số dòng lệnh.
Sao lưu cả `runtime/uploads` cùng dump để giữ ảnh; sao chép `.env`/secrets riêng
vào nơi bảo vệ. Dump chứa dữ liệu cá nhân và hash mật khẩu, không đưa vào gói nộp.

Khôi phục vào **database mới**, cấp quyền user riêng, import dump, copy ảnh, đối
chiếu số bản ghi/hash rồi mới chuyển cấu hình. `scripts/restore_check.py` là công
cụ kiểm chứng cục bộ dùng root của server đang cấu hình; mật khẩu lấy theo
cổng từ `runtime/mysql-PORT-admin-password.local` (bản cũ 3307 dùng
`runtime/root-password.local`). Công cụ không drop/overwrite database.
Các bảng nghiệp vụ phải giống; outbox/session/event có thể tiến triển sau lúc dump.

## Phục hồi và giới hạn

Heartbeat WSS 15s, quá 45s không phản hồi sẽ đóng. Client nghe offline/online và
watchdog, giữ màn hình cũ, khóa gửi mới tới khi SYNC_END; retry theo 1/2/4/8/15s
có jitter. Reload không có model yêu cầu snapshot; có model/cursor hợp lệ thì
replay tối đa 500 event/256KiB. Mỗi socket tối đa 128 frame/512KiB trong hàng đợi.

Khi API trả 503 hoặc mất response, giữ Idempotency-Key/clientOrderId cũ. Nếu trả
409 VERSION_CONFLICT/REQUOTE_REQUIRED, tải lại và xác nhận lại dữ liệu/giá/phí.
Không tạo đơn mới để “thử lại” một đơn chưa biết kết quả.

Lịch sử event/outbox hiện giữ lại để truy vết; cần thiết lập job retention khi vận
hành lâu dài. Xóa outbox đã published trước khi xóa stream event có FK; không xóa
event pending hoặc lịch sử idempotency/đơn chỉ để tiết kiệm dung lượng.

## Quyền truy cập dữ liệu mẫu

Ảnh chat chỉ chủ sở hữu, người thuộc hội thoại hoặc admin được đọc; file được
giải mã, giới hạn pixel và re-encode, tên ngẫu nhiên. Nội dung bị che là bản
canonical; raw vi phạm chỉ admin xem. Không lưu mật khẩu/OTP/session raw vào log.
Log lỗi dùng requestId; production cần giới hạn quyền xem log và thời gian lưu.

## Vòng lặp mạng trên Windows

`scripts/services.ps1` dùng `app.event_loop:new_event_loop`. Windows có dependency
`winloop==0.8.0`; Linux dùng vòng lặp asyncio sẵn có. Nếu thiếu Winloop, chế độ
auto cảnh báo rồi chạy asyncio để app vẫn khởi động; không suy ra có cùng hiệu năng.
Pin nằm trong `backend/requirements.txt`; cài bằng setup hoặc pip trong `.venv`.

Để đối chiếu bằng asyncio, đặt biến trong PowerShell trước khi dừng/chạy lại app:

```powershell
$env:REALTIMEORDERS_EVENT_LOOP = 'asyncio'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 stop-app
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\services.ps1 start
```

Xóa biến với `Remove-Item Env:REALTIMEORDERS_EVENT_LOOP` rồi dừng/chạy lại để về
auto. Không đổi số worker. Kết quả đo và giới hạn ở [LATENCY_2026-10-25.md](LATENCY_2026-10-25.md).
