"""Preview by default; selective deletion of pre-cutoff sales, never a stock return.

Run after migration 0003. Apply requires the exact preview hash and a backup.
Primary database must be in maintenance (backend port 8000 stopped).
"""
import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from datetime import date,datetime,timezone
from pathlib import Path
from socket import create_connection
from sqlalchemy import select,update,delete,or_
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import settings
from app.db import T,Session,engine,reflect,now,public,uid,check
from app.menus import bounds,invalidate
from backup import backup


def fingerprint(data):
    return hashlib.sha256(json.dumps(public(data),sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def preview(s,cutoff):
    cutoff_time=bounds(cutoff)[0]
    orders=sorted((await s.execute(select(T['orders'].c.id).where(T['orders'].c.created_at<cutoff_time))).scalars())
    old=sorted((await s.execute(select(T['offers'].c.id).where(T['offers'].c.sale_date<cutoff))).scalars())
    referenced=set((await s.execute(select(T['order_items'].c.offer_id).where(~T['order_items'].c.order_id.in_(orders)))).scalars())
    referenced.update((await s.execute(select(T['request_quotes'].c.offer_id))).scalars())
    purge=[id for id in old if id not in referenced]
    manifest={'cutoff':str(cutoff),'orderIds':orders,'offerIds':purge,'archiveIds':[id for id in old if id in referenced]}
    return manifest


async def preserved(s,cutoff):
    t=T['orders'];q=select(t).where(t.c.created_at>=bounds(cutoff)[0]).order_by(t.c.id)
    data=[dict(row) for row in (await s.execute(q)).mappings()]
    ids=[r['id'] for r in data]
    children={}
    for name in ('order_items','order_status_history','cancellation_requests'):
        children[name]=[dict(row) for row in (await s.execute(select(T[name]).where(T[name].c.order_id.in_(ids)).order_by(T[name].c.id))).mappings()]
    return {'orders':data,'children':children}


async def apply(s,cutoff,expected):
    manifest=await preview(s,cutoff)
    check(fingerprint(manifest)==expected,'PREVIEW_CHANGED','Danh sách dọn đã thay đổi; tạo bản xem trước mới')
    before=await preserved(s,cutoff)
    order_ids=manifest['orderIds'];offer_ids=manifest['offerIds'];archive_ids=manifest['archiveIds']
    # Keep the stock ledger of retained offers. Detach the deleted sample order;
    # its immutable movement/reference and balance remain as historical evidence.
    ledger=T['inventory_movements']
    await s.execute(update(ledger).where(ledger.c.order_id.in_(order_ids)).values(order_id=None))
    for name in ('cancellation_requests','order_status_history','order_items'):
        await s.execute(delete(T[name]).where(T[name].c.order_id.in_(order_ids)))
    await s.execute(delete(T['orders']).where(T['orders'].c.id.in_(order_ids)))
    for name in ('inventory_movements','offer_prices'):
        await s.execute(delete(T[name]).where(T[name].c.offer_id.in_(offer_ids)))
    await s.execute(delete(T['offers']).where(T['offers'].c.id.in_(offer_ids)))
    await s.execute(update(T['offers']).where(T['offers'].c.id.in_(archive_ids)).values(status='CLOSED',archived_at=now()))
    keys=T['idempotency_keys']
    if order_ids:
        predicate=or_(keys.c.response_body['id'].as_string().in_(order_ids),
                      *(keys.c.scope.like('order:'+id+':%') for id in order_ids))
        await s.execute(delete(keys).where(predicate))
    n=T['notifications']
    await s.execute(delete(n).where(or_(n.c.payload['id'].as_string().in_(order_ids),n.c.payload['offerId'].as_string().in_(manifest['offerIds']+archive_ids))))
    # No old queued fact or cursor can reintroduce deleted entities.
    await s.execute(delete(T['outbox']));await s.execute(delete(T['stream_events']))
    admin=dict((await s.execute(select(T['users']).where(T['users'].c.role=='ADMIN').limit(1))).mappings().one())
    await invalidate(s,admin)
    check(fingerprint(before)==fingerprint(await preserved(s,cutoff)),'PRESERVATION_FAILED','Đơn cần giữ đã thay đổi; rollback')
    await s.execute(T['audit_logs'].insert().values(id=uid(),actor_id=admin['id'],action='sales.cleanup',entity_type='maintenance',
        after_data={'cutoff':str(cutoff),'ordersDeleted':len(order_ids),'offersDeleted':len(offer_ids),'offersArchived':len(archive_ids)},request_id=uid(),created_at=now()))
    return {'ordersDeleted':len(order_ids),'offersDeleted':len(offer_ids),'offersArchived':len(archive_ids),
            'preservedOrders':len(before['orders']),'preservedHash':fingerprint(before),'snapshotRequired':True}


async def main(args):
    database=make_url(settings.database_url).database
    check(database=='realtimeorders' or database.startswith('realtimeorders_audit_'),'WRONG_DATABASE','Chỉ dùng cho CSDL của RealtimeOrders')
    await reflect()
    cutoff=date.fromisoformat(args.before)
    async with Session.begin() as s: manifest=await preview(s,cutoff)
    output={'database':database,'cutoff':str(cutoff),'previewHash':fingerprint(manifest),
            'ordersToDelete':len(manifest['orderIds']),'offersToDelete':len(manifest['offerIds']),'offersToArchive':len(manifest['archiveIds'])}
    if args.apply:
        check(args.expected_hash==output['previewHash'],'PREVIEW_CHANGED','Cần --expected-hash khớp bản xem trước')
        if database=='realtimeorders':
            try:
                with create_connection(('127.0.0.1',8000),timeout=.5): pass
            except OSError: pass
            else: raise RuntimeError('Stop backend before applying primary database cleanup')
        tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uid()[:8]
        folder=ROOT/'runtime/backups'/('sales-cleanup-'+tag);folder.mkdir(parents=True)
        backup(folder/'database.sql',r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe')
        if Path(settings.upload_dir).is_dir():shutil.copytree(settings.upload_dir,folder/'uploads')
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        async with Session.begin() as s: output['result']=await apply(s,cutoff,args.expected_hash)
        output['backup']=str(folder)
    if args.output:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=True))
    await engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',default='2026-10-28');parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-hash');parser.add_argument('--output')
    asyncio.run(main(parser.parse_args()))
