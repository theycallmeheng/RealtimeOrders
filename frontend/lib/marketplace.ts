export function readCart<T>(key: string): T[] {
  try {
    const rows = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    return Array.isArray(rows) ? rows : [];
  } catch {
    return [];
  }
}
