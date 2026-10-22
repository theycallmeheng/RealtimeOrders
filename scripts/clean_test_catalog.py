"""Close only offers explicitly created by our integration tests; preserve history."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.db import T,Session,engine,reflect,now
from sqlalchemy import update

async def main():
    await reflect()
    async with Session.begin() as s:
        result=await s.execute(update(T['offers']).where(T['offers'].c.batch_code.like('TEST-%'),T['offers'].c.status!='CLOSED')
                               .values(status='CLOSED',updated_at=now(),version=T['offers'].c.version+1))
        print('Closed integration-test offers:',result.rowcount)
    await engine.dispose()
asyncio.run(main())
