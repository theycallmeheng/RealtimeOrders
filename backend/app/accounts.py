from sqlalchemy import select, update, func
from .db import T, now, uid, uuid, one, rows, add, change, check, text
from .auth import phone, profile, require_admin
from .commerce import lock_user, version, audit
from .moderation import sanitize
from .events import emit

async def addresses(s,user,method,id,body):
    user=await lock_user(s,user['id'])
    if 'makeDefault' in body:
        check(isinstance(body['makeDefault'],bool),'INVALID_BOOLEAN','Địa chỉ mặc định phải là giá trị đúng/sai')
    t=T['addresses']
    if method=='GET': return await rows(s,'addresses',t.c.user_id==user['id'],t.c.deleted_at==None)
    if id:
        addr=await one(s,'addresses',t.c.id==id,t.c.user_id==user['id'],t.c.deleted_at==None,lock=True)
        version(addr,body)
    if method=='DELETE':
        if user['default_address_id']==id:
            other=await rows(s,'addresses',t.c.user_id==user['id'],t.c.deleted_at==None,t.c.id!=id)
            await change(s,'users',user['id'],default_address_id=other[0]['id'] if other else None,updated_at=now())
        await change(s,'addresses',id,deleted_at=now(),version=addr['version']+1,updated_at=now())
        return {'ok':True}
    if body.get('makeDefault') and id:
        await change(s,'users',user['id'],default_address_id=id,updated_at=now())
        return {'ok':True}
    if not id:
        count=(await s.execute(select(func.count()).select_from(t).where(t.c.user_id==user['id'],t.c.deleted_at==None))).scalar_one()
        check(count<3,'ADDRESS_LIMIT','Chỉ được lưu tối đa 3 địa chỉ',409)
    zone=await one(s,'delivery_zones',T['delivery_zones'].c.id==uuid(body.get('zoneId')),T['delivery_zones'].c.active==True)
    values=dict(zone_id=zone['id'],recipient_name=await sanitize(s,user,text(body.get('recipientName'),100,1),'address.recipient',reject=True),
                phone_e164=phone(body.get('phone')),address_line=await sanitize(s,user,text(body.get('addressLine'),500,5),'address.line',reject=True),
                note=await sanitize(s,user,text(body.get('note',''),500),'address.note'),updated_at=now())
    if body.get('locationToken'):
        from .shipping import verify_location
        location=verify_location(body['locationToken'])
        values.update(latitude=location['latitude'],longitude=location['longitude'],place_id=location['placeId'])
    elif id and values['address_line']!=addr['address_line']:
        values.update(latitude=None,longitude=None,place_id=None)
    if id: await change(s,'addresses',id,version=addr['version']+1,**values)
    else:
        id=uid()
        await add(s,'addresses',id=id,user_id=user['id'],created_at=now(),version=1,**values)
        if not user['default_address_id']: await change(s,'users',user['id'],default_address_id=id,updated_at=now())
    return await one(s,'addresses',t.c.id==id)

async def user_action(s,admin,id,body):
    require_admin(admin)
    check(id!=admin['id'],'SELF_CHANGE','Không thay đổi quyền hoặc khóa chính tài khoản quản trị đang dùng')
    user=await lock_user(s,id)
    version(user,body)
    values={'version':user['version']+1,'updated_at':now()}
    if 'groupId' in body:
        group=await one(s,'customer_groups',T['customer_groups'].c.id==uuid(body['groupId']),T['customer_groups'].c.active==True)
        values['group_id']=group['id']
    if 'status' in body:
        check(body['status'] in ('ACTIVE','LOCKED','DELETED'),'INVALID_STATUS','Trạng thái không hợp lệ')
        check(user['status']!='DELETED' or body['status']=='DELETED','DELETED_USER','Tài khoản đã xóa mềm không được tái sử dụng')
        values['status']=body['status']
    # Any access/group change invalidates old sessions and their catalog subscriptions.
    values['security_version']=user['security_version']+1
    await change(s,'users',id,**values)
    await s.execute(update(T['sessions']).where(T['sessions'].c.user_id==id,T['sessions'].c.revoked_at==None).values(revoked_at=now()))
    emit(s,'user:'+id,'SESSION_REVOKED',{'message':'Quyền tài khoản đã thay đổi; vui lòng đăng nhập lại.'})
    await audit(s,admin,'user.update','user',id,profile(user),values)
    return profile(await one(s,'users',T['users'].c.id==id))
