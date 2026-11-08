import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const account = JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"),"utf8")).accounts[1];
// This QR encodes test text only. No provider request or bank transfer is made.
const testQR = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAMYAAADGAQAAAACh4MLwAAABXklEQVR4nO1YQW6EMAwck9zDD/qU8LOqPwtP6Q/CsZLRVE5gT91qi7rUUolQRLBQRuOxMyDE12Md7gSAK4KLAxzjAGRXXAYyyVBtEUj1oapAsiKwAHNHeDaCbyKLROBDpnXMAESmB945NRIN5KRP3+dIhBVIb/FH7zw3Em1KxNIXr7qA/enwq/sMByOriIyGJ1REzCJyNoI7g/sAoKncluoDW6jQdqOJrFlT8dPf1peCVEQkvE9xk6CXnBppdhzkUBGqtTg/OUWyi7Vpr80+corGW1aY5GBKM7H54Y3WdUkWy6mVRvbEGzbqEs2QtE6iPrAFy2PpbaTLzw82tjwi7eatlYO6wcaNLisEV9iw+1410nIvVfWBLVipWstVWIX2Sz35XhqB8yqCRdz53mXqXdeOCWfY1tE8ecSsi6gfbKm331lG+6KJyD58L251GtiNZXFTC3L9q8HfZ2H4N5FPE1wUvO2pThYAAAAASUVORK5CYII=";
for (const width of [1366, 390]) {
  test(`payOS QR displays, confirms server status and hides expired codes at ${width}px`, async ({page, context}) => {
    if (!process.env.AUDIT_EVIDENCE_DIR) throw new Error("Use isolated_validation.py");
    const login = await context.request.post(origin + "/api/v1/auth/login", {headers:{Origin:origin},data:{identifier:account.phone,password:account.password}});
    expect(login.status()).toBe(200);
    const id = "11111111-1111-4111-8111-111111111111";
    let paid = false, expired = false;
    const order = () => ({id,version:"1",status:"APPROVED",payment_method:"PAYOS",payment_status:paid?"PAID":"UNPAID",payment_deadline:new Date(Date.now()+600000).toISOString(),created_at:new Date().toISOString(),merchandise_total:"100000",shipping_fee:"10000",vat_rate:"0",vat_amount:"0",total:"110000",delivery_method:"INDIVIDUAL",delivery_snapshot:{},address_snapshot:{recipient_name:"Khách kiểm thử",phone_e164:"TEST",address_line:"Địa chỉ kiểm thử"},history:[],cancellation_requests:[],payment:{tracked:true,received:paid?"110000":"0",refunded:"0",remaining:paid?"0":"110000"},items:[{id:"test-item",product_name_snapshot:"Món kiểm thử",quantity:"1",unit_snapshot:"gói",line_total:"100000"}]});
    await page.route("**/api/v1/orders**", async route => {
      const request = route.request(), url = new URL(request.url());
      let data;
      if(request.method()==="GET"&&url.pathname==="/api/v1/orders") data=[order()];
      else if(request.method()==="GET"&&url.pathname==="/api/v1/orders/"+id) data=order();
      else if(request.method()==="POST"&&url.pathname==="/api/v1/orders/"+id+"/payment-link") data={id:"test-request",order_id:id,order_code:100001,amount:"110000",receiver:"PLATFORM",qr_image:testQR,account_name:"Tài khoản kiểm thử",account_number:"TEST-ONLY",checkout_url:"https://pay.payos.vn/web/test-only",expires_at:new Date(Date.now()+(expired?-1000:600000)).toISOString()};
      else return route.continue();
      await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(data)});
    });
    await page.setViewportSize({width,height:844});
    await page.goto("/orders");
    await page.getByRole("button",{name:"Quét QR thanh toán",exact:true}).click();
    const dialog=page.getByRole("dialog",{name:"payOS · Quét QR thanh toán",exact:true});
    await expect(dialog.locator("img")).toBeVisible();
    expect(await dialog.locator("img").evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    paid=true;
    await dialog.getByRole("button",{name:"Kiểm tra trạng thái",exact:true}).click();
    await expect(dialog.getByText("Đã thanh toán thành công",{exact:true})).toBeVisible();
    await expect(dialog.locator("img")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    paid=false;expired=true;
    await page.reload();
    await page.getByRole("button",{name:"Quét QR thanh toán",exact:true}).click();
    await expect(dialog.getByText(/Mã thanh toán không còn hiệu lực/)).toBeVisible();
    await expect(dialog.locator("img")).toHaveCount(0);
  });
}
