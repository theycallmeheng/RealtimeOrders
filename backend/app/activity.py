"""Admin-only history queries; inclusive Vietnamese calendar date filters."""
from datetime import date,timedelta
from sqlalchemy import select
from .db import T,check
from .menus import bounds


def date_range(start=None,end=None):
    def parse(value):
        if not value: return None
        try: result=date.fromisoformat(value)
        except (ValueError,TypeError):
            check(False,'INVALID_DATE','Ngày lọc nhật ký không hợp lệ')
        check(2<=result.year<=9998,'INVALID_DATE','Ngày lọc nằm ngoài phạm vi hỗ trợ')
        return result
    a,b=parse(start),parse(end)
    check(not a or not b or a<=b,'INVALID_DATE_RANGE','Ngày bắt đầu phải trước hoặc bằng ngày kết thúc')
    return bounds(a)[0] if a else None,bounds(b)[1] if b else None


async def history(s,table,params):
    lower,upper=date_range(params.get('startDate'),params.get('endDate'))
    try: page=int(params.get('page','0'))
    except (ValueError,TypeError): page=-1
    check(0<=page<=10000,'INVALID_PAGE','Trang nhật ký không hợp lệ')
    t=T[table]
    q=select(t).order_by(t.c.created_at.desc(),t.c.id.desc()).offset(page*100).limit(100)
    if lower is not None:q=q.where(t.c.created_at>=lower)
    if upper is not None:q=q.where(t.c.created_at<upper)
    result=[dict(r) for r in (await s.execute(q)).mappings()]
    if not result:return []
    actor_key='user_id' if table=='moderation_violations' else 'actor_id'
    ids={r[actor_key] for r in result if r.get(actor_key)}
    u=T['users']
    actors=dict((await s.execute(select(u.c.id,u.c.display_name).where(u.c.id.in_(ids)))).all()) if ids else {}
    for r in result:r['actor_name']=actors.get(r.get(actor_key),'Hệ thống')
    if table=='inventory_movements':
        o,p=T['offers'],T['products']
        ids={r['offer_id'] for r in result}
        names=dict((await s.execute(select(o.c.id,p.c.name).join(p,o.c.product_id==p.c.id).where(o.c.id.in_(ids)))).all())
        for r in result:r['entity_name']=names.get(r['offer_id'],'Mặt hàng đã lưu trữ')
    elif table=='audit_logs':
        tables={'user':('users','display_name'),'product':('products','name'),'customer_groups':('customer_groups','name'),
                'categories':('categories','name'),'units':('units','label'),'delivery_zones':('delivery_zones','name'),
                'pickup_slots':('pickup_slots','name'),'verified_location':('verified_locations','label')}
        for entity,(name,col) in tables.items():
            ids={r['entity_id'] for r in result if r['entity_type']==entity and r['entity_id']}
            if not ids or name not in T or col not in T[name].c:continue
            target=T[name]
            names=dict((await s.execute(select(target.c.id,target.c[col]).where(target.c.id.in_(ids)))).all())
            for r in result:
                if r['entity_type']==entity:r['entity_name']=names.get(r['entity_id'])
        for r in result:
            before,after=r.get('before_data') or {},r.get('after_data') or {}
            r['entity_name']=r.get('entity_name') or after.get('display_name') or before.get('display_name') or after.get('name') or before.get('name')
            if not r['entity_name'] and r['entity_type']=='menu':r['entity_name']='Đợt bán '+str(after.get('sale_date') or before.get('sale_date') or '')
    return result
