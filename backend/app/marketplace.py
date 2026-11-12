"""Shared storefront identity and compatibility with historical shop references."""
from . import auth
from .db import T, check, one

DEFAULT_SHOP = '00000000-0000-4000-8000-000000000001'
PUBLIC_PROFILE_FIELDS = ('description', 'address', 'phone', 'logoUrl', 'coverUrl')


def shop_topic(shop_id):
    return 'shop:' + DEFAULT_SHOP + ':ops'


def assert_owner(user, shop_id):
    check(user['role'] == 'ADMIN' or (
        user['role'] == 'SELLER' and user.get('shop_id') == shop_id
    ), 'FORBIDDEN', 'Dữ liệu thuộc shop khác', 403)


async def get_shop(s, shop_id, active=False, lock=False):
    table = T['shops']
    conditions = [table.c.id == shop_id]
    if active:
        conditions.append(table.c.active.is_(True))
    return await one(s, 'shops', *conditions, lock=lock)


async def manage_shop(s, user, requested=None, lock=False):
    auth.require_shop(user)
    return await get_shop(s, DEFAULT_SHOP, lock=lock)


def public_shop(shop):
    profile = shop['profile_json']
    return {'id': shop['id'], 'name': shop['name'], 'active': shop['active'],
            **{field: profile.get(field, '') for field in PUBLIC_PROFILE_FIELDS}}
