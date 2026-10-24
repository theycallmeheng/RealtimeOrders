# RealtimeOrders implementation instructions

Read docs/SRS.md and docs/DECISIONS.md before implementation. Respect the
distinction between teacher requirements, user-confirmed choices and proposals.
Keep the five workstreams in docs/WORKSTREAMS.md. Optimize within their current
boundaries; do not move features between them or assign members without a user
request. Tests, documentation, integration and operations remain cross-cutting.
Before frontend changes read DESIGN.md and reuse existing components.

The user authorized full implementation on 22 October 2026. Keep the runnable
application, design documents and evidence consistent. Do not claim successful
tests without running them. Do not reuse another project's results.
Do not claim a mock SMS message is a real SMS integration.

Backend owns authorization, price selection, inventory and state transitions.
Persist changes, history and durable events in the same transaction. Never
await network publication or external SMS while holding inventory locks.
Preserve request IDs across retries. Keep HTTP/WSS contracts in PROTOCOL.md.

Use a separate SQLAlchemy session per request/task. Test critical transactions
against MySQL/InnoDB, not SQLite. Every contributor owns their module's tests.
Avoid multi-process WebSocket deployment until a shared event bus is integrated
and tested. Do not introduce microservices for this scope.

Never put credentials, raw session tokens, passwords or OTPs in source or logs.
Keep business decisions explicit; do not silently simplify agreed requirements.
