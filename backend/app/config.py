from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str
    app_secret: str
    app_origin: str = 'https://localhost:3443'
    cookie_secure: bool = True
    demo_mode: bool = False
    sms_provider: str = 'demo'
    email_provider: str = 'demo'
    twilio_account_sid: str = ''
    twilio_auth_token: str = ''
    twilio_from: str = ''
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_from: str = ''
    upload_dir: str = str(ROOT / 'runtime/uploads')
    idle_seconds: int = 1800
    session_seconds: int = 86400

settings = Settings()
if not Path(settings.upload_dir).is_absolute(): settings.upload_dir=str((ROOT/settings.upload_dir).resolve())
if len(settings.app_secret) < 32:
    raise RuntimeError('APP_SECRET phải có ít nhất 32 ký tự')
if settings.sms_provider not in ('demo','twilio') or settings.email_provider not in ('demo','smtp'):
    raise RuntimeError('Nhà cung cấp SMS/email không hợp lệ')
if not settings.demo_mode and (not settings.cookie_secure or not settings.app_origin.startswith('https://')):
    raise RuntimeError('Môi trường thật cần HTTPS và COOKIE_SECURE=true')
if not settings.demo_mode and (settings.sms_provider == 'demo' or settings.email_provider == 'demo'):
    # Email is optional, but a demo SMS must never start in production.
    if settings.sms_provider == 'demo':
        raise RuntimeError('SMS demo cần DEMO_MODE=true')
