"""Creates a dedicated local project DB; never prints generated credentials."""
import asyncio
import secrets
from pathlib import Path
import asyncmy

ROOT = Path(__file__).resolve().parents[1]

async def main():
    env = ROOT / '.env'
    if env.exists():
        print('Đã có cấu hình; không ghi đè.')
        return
    password = secrets.token_hex(24)
    conn = await asyncmy.connect(host='127.0.0.1', port=3307, user='root')
    async with conn.cursor() as c:
        await c.execute('CREATE DATABASE realtimeorders CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        await c.execute("CREATE USER 'realtime'@'127.0.0.1' IDENTIFIED BY %s", (password,))
        await c.execute("GRANT ALL ON realtimeorders.* TO 'realtime'@'127.0.0.1'")
        # Secure the root of this newly initialized isolated instance as well.
        root_password = secrets.token_hex(32)
        await c.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (root_password,))
    conn.close()
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    (runtime / 'root-password.local').write_text(root_password)
    env.write_text(f'DATABASE_URL=mysql+asyncmy://realtime:{password}@127.0.0.1:3307/realtimeorders?charset=utf8mb4\nAPP_SECRET={secrets.token_hex(32)}\nAPP_ORIGIN=https://localhost:3443\nCOOKIE_SECURE=true\nDEMO_MODE=true\nSMS_PROVIDER=demo\nEMAIL_PROVIDER=demo\n', encoding='utf-8')
    print('Đã tạo database riêng và cấu hình cục bộ (secrets được giữ kín).')

asyncio.run(main())
