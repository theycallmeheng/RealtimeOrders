from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from .db import T, now, uid, uuid, one, rows, add, check, text, digest, public
from .commerce import lock_user
from .moderation import sanitize
from .events import emit, notify

async def conversation(s,user,id=None):
    if id:
        result=await one(s,'conversations',T['conversations'].c.id==id)
        check(user['role']=='ADMIN' or result['customer_id']==user['id'],'FORBIDDEN','Hội thoại riêng tư',403)
        return result
    await lock_user(s,user['id'])
    old=await one(s,'conversations',T['conversations'].c.customer_id==user['id'],required=False)
    if old: return old
    return await add(s,'conversations',id=uid(),customer_id=user['id'],created_at=now())

async def messages(s,user,id,before=None):
    await conversation(s,user,id)
    t=T['messages']; conditions=[t.c.conversation_id==id]
    if before:
        cursor=await one(s,'messages',t.c.id==before,t.c.conversation_id==id)
        conditions.append((t.c.created_at<cursor['created_at']) | ((t.c.created_at==cursor['created_at']) & (t.c.id<cursor['id'])))
    data=await rows(s,'messages',*conditions,limit=50,order=[t.c.created_at.desc(),t.c.id.desc()])
    data.reverse()
    for m in data:
        m.pop('request_hash',None)
        m['attachments']=await rows(s,'message_attachments',T['message_attachments'].c.message_id==m['id'])
    return public(data)

async def send(s,user,body):
    check(isinstance(body,dict),'INVALID_MESSAGE','Nội dung tin nhắn không hợp lệ')
    await lock_user(s,user['id'])
    conv=await conversation(s,user,uuid(body.get('conversationId')))
    clientid=uuid(body.get('clientMessageId'))
    old=await one(s,'messages',T['messages'].c.sender_id==user['id'],T['messages'].c.client_message_id==clientid,required=False)
    if old:
        check(old['request_hash']==digest(body),'IDEMPOTENCY_CONFLICT','Mã tin đã được dùng cho nội dung khác',409)
        old.pop('request_hash',None)
        old['attachments']=await rows(s,'message_attachments',T['message_attachments'].c.message_id==old['id'])
        return public(old)
    content=text(body.get('text',''),4000)
    assets=body.get('assetIds',[])
    check(isinstance(assets,list) and len(assets)<=3 and (content or assets),
          'EMPTY_MESSAGE','Tin nhắn cần nội dung hoặc tối đa 3 ảnh')
    assets=[uuid(asset) for asset in assets]
    check(len(set(assets))==len(assets),'INVALID_IMAGES','Mỗi ảnh chỉ được chọn một lần')
    id=uid()
    clean=await sanitize(s,user,content,'chat.text',id)
    for asset in assets:
        media=await one(s,'media_assets',T['media_assets'].c.id==uuid(asset),T['media_assets'].c.owner_id==user['id'],
                        T['media_assets'].c.purpose=='CHAT',T['media_assets'].c.state=='READY')
    m=await add(s,'messages',id=id,conversation_id=conv['id'],sender_id=user['id'],client_message_id=clientid,
                request_hash=digest(body),text_sanitized=clean,created_at=now())
    for position,asset in enumerate(assets): await add(s,'message_attachments',message_id=id,asset_id=asset,position=position)
    m.pop('request_hash')
    m['attachments']=[{'asset_id':a,'position':i} for i,a in enumerate(assets)]
    for topic in ('user:'+conv['customer_id'],'admin:ops'): emit(s,topic,'CHAT_MESSAGE',public(m),id)
    if user['role']=='ADMIN': await notify(s,conv['customer_id'],'CHAT_MESSAGE',{'conversationId':conv['id'],'message':'Người bán vừa gửi tin nhắn.'})
    return public(m)
