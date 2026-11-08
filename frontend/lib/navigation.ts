export const CUSTOMER_ROUTES: Record<string, string> = {
  feed: "/feed",
  catalog: "/menu", checkout: "/cart", orders: "/orders", chat: "/messages",
  profile: "/profile", apply: "/open-shop", notifications: "/notifications", requests: "/product-requests",
};
export const ADMIN_ROUTES: Record<string, string> = {
  orders: "/admin/orders", offers: "/admin/menus", products: "/admin/products",
  chat: "/admin/messages", users: "/admin/customers", config: "/admin/settings",
  reports: "/admin/reports", audit: "/admin/audit", notifications: "/admin/notifications",
  shop: "/admin/shop", staff: "/admin/staff", finance: "/admin/finance", withdrawals: "/admin/withdrawals", reviews: "/admin/reviews",
  requests: "/admin/product-requests",
};
export const SELLER_ROUTES: Record<string, string> = {
  reports: "/shop/reports",
  orders: "/shop/orders", offers: "/shop/menus", products: "/shop/products",
  chat: "/shop/messages", shop: "/shop/profile", balance: "/shop/balance",
  reviews: "/shop/reviews", notifications: "/shop/notifications",
  requests: "/shop/product-requests",
};
export const COURIER_ROUTES = { orders: "/courier/orders", notifications: "/courier/notifications" };
export const applicationPaths = [...Object.values(CUSTOMER_ROUTES), ...Object.values(ADMIN_ROUTES), ...Object.values(SELLER_ROUTES), ...Object.values(COURIER_ROUTES), "/login"];
export const routesForRole = (role: string): Record<string,string> => role === "ADMIN" ? ADMIN_ROUTES : role === "SELLER" ? SELLER_ROUTES : role === "SHIPPER" ? COURIER_ROUTES : CUSTOMER_ROUTES;
export function tabForPath(role: string, path: string): string | undefined {
  const normalized = path.replace(/\/+$/, "") || "/";
  return Object.entries(routesForRole(role)).find(([, value]) => value === normalized)?.[0];
}
export function pathForTab(role: string, tab: string): string | undefined {
  return routesForRole(role)[tab];
}
