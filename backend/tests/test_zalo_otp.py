from contextlib import asynccontextmanager
from datetime import timedelta
import json

import httpx
import pytest
from sqlalchemy import Column, MetaData, String, Table

from app import auth
from app.db import Fault, now


class MemorySessions:
    @asynccontextmanager
    async def begin(self):
        yield object()


class ChallengeStore:
    def __init__(self):
        self.rows = {}
        self.users = {}

    def install(self, monkeypatch):
        metadata = MetaData()
        challenge_table = Table(
            "auth_challenges", metadata,
            Column("id", String), Column("purpose", String), Column("subject", String),
            Column("user_id", String),
        )
        user_table = Table("users", metadata, Column("phone_e164", String))
        monkeypatch.setattr(auth, "T", {"auth_challenges": challenge_table, "users": user_table})
        monkeypatch.setattr(auth, "Session", MemorySessions())
        monkeypatch.setattr(auth, "rate", self.rate)
        monkeypatch.setattr(auth, "add", self.add)
        monkeypatch.setattr(auth, "change", self.change)
        monkeypatch.setattr(auth, "one", self.one)

    async def rate(self, key, limit, seconds):
        return None

    async def add(self, session, table, **values):
        self.rows.setdefault(table, {})[values["id"]] = dict(values)
        return values

    async def change(self, session, table, row_id, **values):
        self.rows[table][row_id].update(values)

    async def one(self, session, table, *conditions, lock=False, required=True):
        found = None
        if table == "auth_challenges":
            for row in self.rows.get(table, {}).values():
                if all(row.get(condition.left.name) == condition.right.value for condition in conditions):
                    found = row
                    break
        if table == "users":
            for row in self.users.values():
                if all(row.get(condition.left.name) == condition.right.value for condition in conditions):
                    found = row
                    break
        if required and found is None:
            raise Fault("NOT_FOUND", "Không tìm thấy dữ liệu", 404)
        return dict(found) if found else None


@pytest.mark.asyncio
async def test_zbs_template_phone_payload(monkeypatch):
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    monkeypatch.setattr(auth.settings, "zalo_otp_code_field", "verification_code")
    request = {}

    def handle(incoming):
        request["url"] = str(incoming.url)
        request["headers"] = incoming.headers
        request["json"] = json.loads(incoming.content)
        return httpx.Response(200, json={"error": 0, "message": "Success"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: client_type(
        *args, transport=httpx.MockTransport(handle), **kwargs))
    assert await auth.send_zalo_code("+84912345678", "123456") is True
    assert request["url"] == "https://business.openapi.zalo.me/message/template"
    assert request["headers"]["access_token"] == "test-access-token"
    payload = request["json"]
    assert payload["phone"] == "84912345678"
    assert payload["template_id"] == "otp-template-17"
    assert payload["template_data"] == {"verification_code": "123456"}
    tracking_id = payload["tracking_id"]
    assert len(tracking_id) == 32 and all(char in "0123456789abcdef" for char in tracking_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(200, {"error": 1001}), (503, {"error": 0})])
async def test_zbs_provider_rejection_is_not_success(monkeypatch, status, body):
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    client_type = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: client_type(
        *args, transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)), **kwargs))
    assert await auth.send_zalo_code("+84912345678", "123456") is False


@pytest.mark.asyncio
async def test_registration_rate_limit_stops_delivery(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", False)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")

    async def limited(*_):
        raise Fault("RATE_LIMITED", "Thao tác quá nhanh", 429)

    async def must_not_send(*_):
        raise AssertionError("rate-limited registration must not call provider")

    monkeypatch.setattr(auth, "rate", limited)
    monkeypatch.setattr(auth, "send_zalo_code", must_not_send)
    with pytest.raises(Fault) as failure:
        await auth.registration_challenge("+84910000000", "test-ip")
    assert failure.value.code == "RATE_LIMITED"
    assert store.rows.get("auth_challenges", {}) == {}


@pytest.mark.asyncio
async def test_no_zalo_configuration_is_explicit_demo_only(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", True)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "")
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: 314159)

    result = await auth.registration_challenge("+84910000001", "test-ip")
    assert result["channel"] == "demo"
    assert result["deliveryStatus"] == "demo"
    assert result["demoCode"] == "314159"
    assert "test-access-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_zalo_success_waits_60_seconds_then_sms_invalidates_old_code(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", False)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    codes = iter([123456, 654321])
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: next(codes))
    sent_zalo, sent_sms = [], []

    async def send_zalo(phone, code):
        sent_zalo.append((phone, code))
        return True

    async def send_sms(phone, code, purpose):
        sent_sms.append((phone, code, purpose))
        return "sms"

    monkeypatch.setattr(auth, "send_zalo_code", send_zalo)
    monkeypatch.setattr(auth, "send_code", send_sms)
    first = await auth.registration_challenge("+84912345678", "test-ip")
    assert first["channel"] == "zalo" and first["deliveryStatus"] == "accepted"
    assert first["fallbackAfterSeconds"] == 60 and "demoCode" not in first
    with pytest.raises(Fault) as early:
        await auth.sms_fallback(first["challengeId"], "test-ip")
    assert early.value.code == "SMS_FALLBACK_WAIT"
    store.rows["auth_challenges"][first["challengeId"]]["delivery_accepted_at"] = now() - timedelta(seconds=61)

    second = await auth.sms_fallback(first["challengeId"], "test-ip")
    assert second["channel"] == "sms" and second["deliveryStatus"] == "accepted"
    assert sent_zalo == [("+84912345678", "123456")]
    assert sent_sms == [("+84912345678", "654321", "REGISTER_PHONE")]
    original = store.rows["auth_challenges"][first["challengeId"]]
    assert original["state"] == "FAILED" and original["sms_fallback_used_at"] is not None
    with pytest.raises(Fault) as old_code:
        await auth.verify_challenge(first["challengeId"], "123456", "REGISTER_PHONE")
    assert old_code.value.code == "OTP_EXPIRED"
    verified = await auth.verify_challenge(second["challengeId"], "654321", "REGISTER_PHONE")
    assert verified["ticket"]
    with pytest.raises(Fault) as replay:
        await auth.verify_challenge(second["challengeId"], "654321", "REGISTER_PHONE")
    assert replay.value.code == "OTP_EXPIRED"
    with pytest.raises(Fault) as second_fallback:
        await auth.sms_fallback(first["challengeId"], "test-ip")
    assert second_fallback.value.code == "SMS_FALLBACK_USED"


@pytest.mark.asyncio
async def test_zalo_rejection_allows_immediate_sms_fallback(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", False)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    codes = iter([111111, 222222])
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: next(codes))
    monkeypatch.setattr(auth, "send_zalo_code", lambda *_: _async_value(False))
    sent = []

    async def send_sms(phone, code, purpose):
        sent.append(code)
        return "sms"

    monkeypatch.setattr(auth, "send_code", send_sms)
    first = await auth.registration_challenge("+84987654321", "test-ip")
    assert first["deliveryStatus"] == "unavailable" and first["fallbackAvailable"] is True
    second = await auth.sms_fallback(first["challengeId"], "test-ip")
    assert second["channel"] == "sms" and sent == ["222222"]
    with pytest.raises(Fault) as old_code:
        await auth.verify_challenge(first["challengeId"], "111111", "REGISTER_PHONE")
    assert old_code.value.code == "OTP_EXPIRED"


@pytest.mark.asyncio
async def test_failed_sms_fallback_invalidates_both_codes(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", False)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    codes = iter([333333, 444444])
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: next(codes))
    monkeypatch.setattr(auth, "send_zalo_code", lambda *_: _async_value(False))

    async def failed_sms(*_):
        raise RuntimeError("provider details must not escape")

    monkeypatch.setattr(auth, "send_code", failed_sms)
    first = await auth.registration_challenge("+84922223333", "test-ip")
    with pytest.raises(Fault) as failure:
        await auth.sms_fallback(first["challengeId"], "test-ip")
    assert failure.value.code == "SMS_UNAVAILABLE"
    assert "provider details" not in failure.value.message
    rows = list(store.rows["auth_challenges"].values())
    assert len(rows) == 2
    assert all(row["state"] == "FAILED" for row in rows)


@pytest.mark.asyncio
async def test_otp_expires_after_five_minutes(monkeypatch):
    store = ChallengeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(auth.settings, "demo_mode", False)
    monkeypatch.setattr(auth.settings, "zalo_access_token", "test-access-token")
    monkeypatch.setattr(auth.settings, "zalo_otp_template_id", "otp-template-17")
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: 555555)

    async def send_zalo(*_):
        return True

    monkeypatch.setattr(auth, "send_zalo_code", send_zalo)
    challenge = await auth.registration_challenge("+84911112222", "test-ip")
    store.rows["auth_challenges"][challenge["challengeId"]]["expires_at"] = now() - timedelta(seconds=1)
    with pytest.raises(Fault) as expired:
        await auth.verify_challenge(challenge["challengeId"], "555555", "REGISTER_PHONE")
    assert expired.value.code == "OTP_EXPIRED"


async def _async_value(value):
    return value
