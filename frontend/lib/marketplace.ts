export const DEFAULT_SHOP = "00000000-0000-4000-8000-000000000001";
export const storefrontShopKey = (userId: string) => "ro-storefront-shop-" + userId;
export const chatShopKey = (userId: string) => "ro-chat-shop-" + userId;
export const shopOf = (row: { shop_id?: string }) => row.shop_id || DEFAULT_SHOP;

export function readCart<T>(key: string): T[] {
  try {
    const rows = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}

export function clearShopCart<T extends { shop_id?: string }>(key: string, shopId: string): T[] {
  const remaining = readCart<T>(key).filter((item) => shopOf(item) !== shopId);
  sessionStorage.setItem(key, JSON.stringify(remaining));
  return remaining;
}
