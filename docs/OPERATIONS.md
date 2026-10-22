# Cài đặt và vận hành RealtimeOrders

## Một máy Windows

README mô tả setup/start/stop. `runtime/services.local.json` chỉ chứa PID, thời
điểm tạo và dấu hiệu lệnh; script dừng chỉ những tiến trình còn khớp cả ba điều kiện.
Không dừng dịch vụ MySQL của người dùng. Instance MySQL do setup tạo có thư mục
riêng; root password nằm trong `runtime/root-password.local`, không đưa lên Git/Drive.
Không tự xóa `runtime/mysql-data` hoặc chạy lại initialize trên thư mục cũ.

Trên máy bàn giao hiện tại, datadir hoạt động là
`D:\Dev PTIT\RealtimeOrders-data\mysql-data` (ASCII), được ghi trong
`runtime/mysql.local.json`. Binary MySQL 8.0.46 đã báo lỗi khi mở datadir có dấu.
`runtime/mysql-data` trong project là bản sao lạnh lúc chuyển dữ liệu, không phải
instance đang chạy. Bản gốc ở thư mục staging C cũng giữ để dự phòng; không dùng
các bản sao này để chạy đồng thời cùng cổng. Backup thường xuyên phải lấy từ DB
hoạt động qua `DATABASE_URL` và ảnh trong runtime/uploads của bản bàn giao.

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
cụ kiểm chứng cục bộ dùng root của instance riêng; không drop/overwrite database.
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
