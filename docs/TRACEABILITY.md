# Đối chiếu yêu cầu — thiết kế — kiểm thử

Bảng này đối chiếu yêu cầu, module và mã test được mô tả trong
[TEST_PLAN.md](TEST_PLAN.md). Bảng không xác nhận test đã chạy hoặc đã đạt. FR12
thuộc thiết kế ban đầu; phiên bản hiện tại đã rút chức năng yêu cầu hàng/báo giá.
Xem [DAILY_SALES.md](DAILY_SALES.md).

| Yêu cầu | Module/thiết kế chính | Ca kiểm tra |
| --- | --- | --- |
| FR01 | auth_challenges, OTP adapter, auth API | TC01–02 |
| FR02 | users/sessions, role, thu hồi socket | TC02–03,19,24 |
| FR03 | addresses/default FK + account lock | TC04 |
| FR04 | admin users, group/version, audit | TC03,05,24 |
| FR05 | catalog/offers/units/media | TC06,08,25 |
| FR06 | group price, offer stats, catalog stream | TC05,08,20 |
| FR07 | delivery_zones/policies/pickup_slots | TC07–08 |
| FR08 | checkout/order_items/snapshot | TC06,08–09 |
| FR09 | InnoDB transaction, offer locks, ledger | TC10–11,21–22 |
| FR10 | state machine/history/version | TC12–13 |
| FR11 | cancellation_requests/CANCEL_RESTORE | TC12–13 |
| FR12 | Rút khỏi phạm vi; API cũ trả HTTP 410 | — |
| FR13 | conversation/message/assets | TC15,19,25 |
| FR14 | notifications/subscriptions/fan-out jobs | TC17,20,22,27 |
| FR15 | moderation rules/violations + server service | TC16,19 |
| FR16 | reports/query UTC range + delivered totals | TC18 |
| FR17 | PROTOCOL, stream ACL, sync/hub | TC19–24 |
| FR18 | idempotency/stream/outbox/notification jobs | TC09–11,15,21–22,27 |
| FR19 | auth limits, permissions, file/SQL safeguards | TC01–05,15–16,19,24–25 |
| FR20 | DESIGN, customer/admin UI | TC26 |
| NFR01 | Invariants transaction/ledger | TC09–13,21–22; E1 |
| NFR02 | TLS/session/CSRF/Origin/private media | TC03,05,15,19,24–25 |
| NFR03 | Controlled load profiles | E2–E3 |
| NFR04–05 | Latency/error classification and metrics | E2–E3 |
| NFR06 | Bounded queue/replay/snapshot | TC20–23; E3 |
| NFR07 | Evidence/raw/clock/reproducibility | E1–E3 |
| NFR08 | Source runbook/migration/backup | TC28, release rehearsal |

Mã test chỉ mô tả kịch bản dự kiến trong TEST_PLAN; cần chạy test trên môi trường
phù hợp trước khi kết luận trạng thái. Kết quả từng lần chạy được lưu cục bộ,
không commit cùng source.
