import {test,expect} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const origin=process.env.APP_ORIGIN ?? "https://localhost:3443";
const accounts=JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"),"utf8")).accounts;
test.use({ignoreHTTPSErrors:new URL(origin).hostname === "localhost"});
test("monthly totals, day breakdown, comparison and CSV", async ({page,context})=>{
 const a=accounts[0];const login=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:a.phone,password:a.password}});
 expect(login.status()).toBe(200);const session=await login.json();
 try{
  const invalid=await context.request.get(origin+"/api/v1/admin/reports/monthly?month=2026-13");expect(invalid.status()).toBe(400);
  const result=await context.request.get(origin+"/api/v1/admin/reports/monthly?month=2026-10&compare=2026-09");expect(result.status()).toBe(200);const report=await result.json();
  expect(report.daily.length).toBe(31);
  expect(report.daily.reduce((n:number,r:any)=>n+r.orders,0)).toBe(report.selected.orders);
  expect(report.daily.reduce((n:bigint,r:any)=>n+BigInt(r.merchandise),BigInt(0)).toString()).toBe(report.selected.merchandise);
  await page.goto(origin+"/admin/reports");
  await page.getByRole("button",{name:"Theo tháng",exact:true}).click();
  await page.getByLabel("Tháng báo cáo",{exact:true}).fill("2026-10");
  await page.getByLabel("So sánh với",{exact:true}).fill("2026-09");
  await expect(page.locator("tbody tr")).toHaveCount(31);
  await expect(page.locator(".report-totals").locator(".report-value").first()).toHaveText(String(report.selected.orders));
  const download=page.waitForEvent("download");await page.getByRole("button",{name:"Xuất CSV",exact:true}).click();const csv=await download;
  expect(csv.suggestedFilename()).toBe("lai-gop-2026-10.csv");const stream=await csv.createReadStream();let text="";for await(const part of stream!)text+=part.toString("utf8");
  expect(text.trim().split("\n")).toHaveLength(32);expect(text).toContain("2026-10-31");
  await page.getByLabel("So sánh với",{exact:true}).fill("2026-10");await expect(page.getByText(/So với 2026-10: Không đổi/).first()).toBeVisible();
  await page.getByLabel("Tháng báo cáo",{exact:true}).fill("2024-02");await expect(page.locator("tbody tr")).toHaveCount(29);
  await page.setViewportSize({width:360,height:820});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
  await page.screenshot({path:"../runtime/browser-test-results/monthly-reports-mobile.png"});
  await page.getByRole("button",{name:"Theo ngày",exact:true}).click();await expect(page.getByLabel("Ngày báo cáo",{exact:true})).toBeVisible();await expect(page.locator("tbody tr")).toHaveCount(7);
 }finally{await context.request.post(origin+"/api/v1/auth/logout",{headers:{Origin:origin,"X-CSRF-Token":session.csrfToken}})}
});
test("customer cannot read monthly financial reports",async ({context})=>{
 const a=accounts[1];const r=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:a.phone,password:a.password}});expect(r.status()).toBe(200);const session=await r.json();
 try{expect((await context.request.get(origin+"/api/v1/admin/reports/monthly?month=2026-10")).status()).toBe(403)}
 finally{await context.request.post(origin+"/api/v1/auth/logout",{headers:{Origin:origin,"X-CSRF-Token":session.csrfToken}})}
});
