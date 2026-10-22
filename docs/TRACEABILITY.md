# Đối chiếu yêu cầu — thiết kế — kiểm thử

Trạng thái ban đầu của mọi dòng: **đã đặc tả, chưa triển khai/chạy test**.
Các ngày là mục tiêu tích hợp, không phải ngày hoàn thành đã ghi nhận.

| Yêu cầu | Module/thiết kế chính | Ca kiểm tra | Mục tiêu |
|---|---|---|---|
| FR01 | auth_challenges, OTP adapter, auth API | TC01–02 | 23/10 |
| FR02 | users/sessions, role, thu hồi socket | TC02–03,19,24 | 23/10 |
| FR03 | addresses/default FK + account lock | TC04 | 23/10 |
| FR04 | admin users, group/version, audit | TC03,05,24 | 24–26/10 |
| FR05 | catalog/offers/units/media | TC06,08,25 | 24/10 |
| FR06 | group price, offer stats, catalog stream | TC05,08,20 | 24–27/10 |
| FR07 | delivery_zones/policies/pickup_slots | TC07–08 | 24/10 |
| FR08 | checkout/order_items/snapshot | TC06,08–09 | 25/10 |
| FR09 | InnoDB transaction, offer locks, ledger | TC10–11,21–22 | 25/10 |
| FR10 | state machine/history/version | TC12–13 | 26/10 |
| FR11 | cancellation_requests/CANCEL_RESTORE | TC12–13 | 26/10 |
| FR12 | product_requests/quotes/convert | TC14 | 28/10 |
| FR13 | conversation/message/assets | TC15,19,25 | 28/10 |
| FR14 | notifications/subscriptions/fan-out jobs | TC17,20,22,27 | 27/10 |
| FR15 | moderation rules/violations + server service | TC16,19 | 28/10 |
| FR16 | reports/query UTC range + delivered totals | TC18 | 28/10 |
| FR17 | PROTOCOL, stream ACL, sync/hub | TC19–24 | 27/10 |
| FR18 | idempotency/stream/outbox/notification jobs | TC09–11,15,21–22,27 | 25–27/10 |
| FR19 | auth limits, permissions, file/SQL safeguards | TC01–05,15–16,19,24–25 | 23–29/10 |
| FR20 | DESIGN, customer/admin UI | TC26 | 24–29/10 |
| NFR01 | Invariants transaction/ledger | TC09–13,21–22; E1 | 25–30/10 |
| NFR02 | TLS/session/CSRF/Origin/private media | TC03,05,15,19,24–25 | 23–29/10 |
| NFR03 | Controlled load profiles | E2–E3 | 30/10 |
| NFR04–05 | Latency/error classification and metrics | E2–E3 | 30/10 |
| NFR06 | Bounded queue/replay/snapshot | TC20–23; E3 | 27–30/10 |
| NFR07 | Evidence/raw/clock/reproducibility | E1–E3 | 30/10 |
| NFR08 | Source runbook/migration/backup | TC28, release rehearsal | 29–31/10 |

Chức năng có UI nhưng chưa nối backend, dùng SMS giả, chưa kiểm thử TLS hoặc
chưa đo 2.000 người phải ghi đúng trạng thái trong báo cáo triển khai sau này.
Nhóm cập nhật cột bằng chứng bằng log/commit/run ID khi làm thật, không tự đổi
toàn bộ thành “đạt” lúc tạo bộ đặc tả.
