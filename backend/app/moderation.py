import re
import unicodedata
from .db import rows, add, now, uid, check
from .events import emit

async def sanitize(s, user, value, field, reference=None, reject=False):
    value = unicodedata.normalize('NFC', value)
    result, hits = value, []
    for rule in await rows(s, 'moderation_rules', limit=1000):
        if not rule['active']: continue
        pattern = re.escape(rule['phrase_normalized'])
        if rule['match_mode'] == 'TOKEN': pattern = r'(?<!\w)' + pattern + r'(?!\w)'
        result, count = re.subn(pattern, lambda m: '*' * len(m.group()), result, flags=re.IGNORECASE)
        if count: hits.append(rule)
    if reject: check(not hits, 'CONTENT_REJECTED', 'Địa chỉ có nội dung không phù hợp; vui lòng sửa')
    if hits and user:
        id = uid()
        await add(s, 'moderation_violations', id=id, user_id=user['id'], rule_id=hits[0]['id'], field_name=field,
                  reference_id=reference, original_restricted=value, sanitized=result, created_at=now())
        emit(s, 'admin:ops', 'MODERATION_WARNING', {'id': id, 'userId': user['id'], 'field': field})
        emit(s, 'user:'+user['id'], 'CONTENT_WARNING', {'message': 'Nội dung không phù hợp đã được che.'})
    return result
