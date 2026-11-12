type PriceGroup = { id: string; code: string; active: boolean };

// Integer arithmetic keeps rounding identical to the server (half up, VND).
type PricingRules = { markupPercent: number; groupPercent: Record<string, number> };
const defaults: PricingRules = {markupPercent: 150, groupPercent: {STUDENT: 95, WORKER: 100, VIP: 90}};
export function menuPrices(cost: unknown, groups: PriceGroup[], configured?: PricingRules | null) {
  const rules = configured ?? defaults;
  const value = String(cost ?? "").trim();
  const valid = /^\d+(?:\.\d{1,6})?$/.test(value);
  const [whole, fraction = ""] = value.split(".");
  const units = valid ? BigInt(whole + fraction.padEnd(6, "0")) : 0n;
  const base = (units * BigInt(rules.markupPercent) + 50000000n) / 100000000n;
  return groups.filter((g) => g.active).map((g) => {
    const percent = BigInt(rules.groupPercent[g.code] ?? 100);
    return { groupId: g.id, unitPrice: valid ? ((base * percent + 50n) / 100n).toString() : "" };
  });
}
