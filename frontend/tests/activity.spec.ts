import {test,expect} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {activityLabel,changedFields} from "../lib/activity-labels";
const origin=process.env.APP_ORIGIN ?? "https://localhost:3443";
const accounts=JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"),"utf8")).accounts;
test.use({ignoreHTTPSErrors:new URL(origin).hostname === "localhost"});
test("human action labels explain state transitions",()=>{
 expect(activityLabel({action:"user.update",before_data:{status:"ACTIVE"},after_data:{status:"DELETED"}})).toBe("Xóa mềm tài khoản");
 expect(activityLabel({action:"user.update",before_data:{status:"LOCKED"},after_data:{status:"ACTIVE"}})).toBe("Mở khóa tài khoản");
 expect(activityLabel({action:"menu.save",before_data:{status:"OPEN"},after_data:{status:"CLOSED"}})).toBe("Đóng đợt bán");
 expect(activityLabel({kind:"CANCEL_RESTORE"})).toBe("Hoàn kho khi hủy đơn");
 expect(changedFields({before_data:{status:"ACTIVE",version:1},after_data:{status:"DELETED",version:2,security_version:2}})).toEqual(["status"]);
});
test("all log types filter inclusive VN dates; UI explains changes",async({page,context})=>{
 const a=accounts[0],r=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:a.phone,password:a.password}});expect(r.status()).toBe(200);const session=await r.json();
 try{
  const start="2026-10-30T17:00:00Z",end="2026-10-31T17:00:00Z";
  for(const kind of ["audit","inventory-movements","moderation/violations"]){
   const response=await context.request.get(origin+`/api/v1/admin/${kind}?startDate=2026-10-31&endDate=2026-10-31`);expect(response.status()).toBe(200);
   const data=await response.json();for(const row of data){expect(Date.parse(row.created_at)).toBeGreaterThanOrEqual(Date.parse(start));expect(Date.parse(row.created_at)).toBeLessThan(Date.parse(end));expect(typeof row.actor_name).toBe("string")}
   const invalid=await context.request.get(origin+`/api/v1/admin/${kind}?startDate=2026-11-01&endDate=2026-10-31`);expect(invalid.status()).toBe(400);
  }
  await page.goto(origin+"/admin/audit");await page.getByLabel("Từ ngày",{exact:true}).fill("2026-10-31");await page.getByLabel("Đến ngày",{exact:true}).fill("2026-10-31");await page.getByRole("button",{name:"Lọc nhật ký",exact:true}).click();
  await expect(page.getByRole("columnheader",{name:"Người thực hiện",exact:true})).toBeVisible();
  await expect(page.locator("tbody").getByText("Xóa mềm tài khoản",{exact:true}).first()).toBeVisible();
  const row=page.locator("tbody tr").filter({hasText:"Xóa mềm tài khoản"}).first();await expect(row).toContainText("Nguyễn Ánh");await expect(row).toContainText("Đã xóa");
  const raw=row.locator("details");await expect(raw).not.toHaveAttribute("open","");await raw.locator("summary").click();await expect(raw.locator("pre")).toBeVisible();
  await page.getByLabel("Từ ngày",{exact:true}).fill("2030-01-01");await page.getByLabel("Đến ngày",{exact:true}).fill("2030-01-02");await page.getByRole("button",{name:"Lọc nhật ký",exact:true}).click();await expect(page.getByText("Không có bản ghi trong phạm vi ngày này",{exact:true})).toBeVisible();
  await page.setViewportSize({width:360,height:820});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
 }finally{await context.request.post(origin+"/api/v1/auth/logout",{headers:{Origin:origin,"X-CSRF-Token":session.csrfToken}})}
});
test("customer cannot read audit logs",async({context})=>{
 const a=accounts[1],r=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:a.phone,password:a.password}});expect(r.status()).toBe(200);const session=await r.json();
 try{for(const kind of ["audit","inventory-movements","moderation/violations"])expect((await context.request.get(origin+"/api/v1/admin/"+kind)).status()).toBe(403)}
 finally{await context.request.post(origin+"/api/v1/auth/logout",{headers:{Origin:origin,"X-CSRF-Token":session.csrfToken}})}
});
