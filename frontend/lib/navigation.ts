export const CUSTOMER_ROUTES: Record<string, string> = {
  catalog: "/menu", checkout: "/cart", orders: "/orders", chat: "/messages",
  profile: "/profile", notifications: "/notifications",
};
export const ADMIN_ROUTES: Record<string, string> = {
  orders: "/admin/orders", offers: "/admin/menus", products: "/admin/products",
  chat: "/admin/messages", users: "/admin/customers", config: "/admin/settings",
  reports: "/admin/reports", audit: "/admin/audit", notifications: "/admin/notifications",
};
export const applicationPaths = [...Object.values(CUSTOMER_ROUTES), ...Object.values(ADMIN_ROUTES), "/login"];
export const routesForRole = (role: string) => role === "ADMIN" ? ADMIN_ROUTES : CUSTOMER_ROUTES;
export function tabForPath(role: string, path: string): string | undefined {
  const normalized = path.replace(/\/+$/, "") || "/";
  return Object.entries(routesForRole(role)).find(([, value]) => value === normalized)?.[0];
}
export function pathForTab(role: string, tab: string): string | undefined {
  return routesForRole(role)[tab];
}
