import { test, expect, BrowserContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
const origin=process.env.APP_ORIGIN??"https://localhost:3443";
const accounts=JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"),"utf8")).accounts;
let seller:any,courier:any,product:any,privateProduct:any,menu:any,oldVat:any;
const day=()=>new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Ho_Chi_Minh"});
async function login(context:BrowserContext,a:any){const r=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:a.phone,password:a.password}});expect(r.status()).toBe(200);return r.json();}
async function call(context:BrowserContext,s:any,method:string,url:string,body?:any){const r=await context.request.fetch(origin+"/api/v1"+url,{method,headers:{Origin:origin,"X-CSRF-Token":s.csrfToken,"Idempotency-Key":crypto.randomUUID()},data:body});expect(r.status(),await r.text()).toBe(200);return r.json();}
async function screenshot(page:any,name:string){await page.screenshot({path:path.join(process.env.AUDIT_EVIDENCE_DIR!,name+".png"),fullPage:true});}
test.beforeAll(async({browser})=>{
 if(!process.env.AUDIT_EVIDENCE_DIR)throw new Error("Business browser tests require isolated_validation.py");
 const context=await browser.newContext({ignoreHTTPSErrors:true});const admin=await login(context,accounts[0]);
 for(const role of ["SELLER","SHIPPER"]){const credentials={name:"Browser "+role,phone:"+849"+String(crypto.randomInt(10000000,99999999)),password:"IsolatedBrowser123!",role};const saved=await call(context,admin,"POST","/admin/staff",credentials);if(role==="SELLER")seller={...credentials,...saved};else courier={...credentials,...saved};}
 const products=await call(context,admin,"GET","/admin/products"),groups=await call(context,admin,"GET","/admin/config/groups");
 const template=products.find((p:any)=>p.active&&!p.deleted_at),worker=groups.find((g:any)=>g.code==="WORKER");
 const base={categoryId:template.category_id,unitId:template.unit_id,quantityStep:"1",defaultCostPrice:"20000"};
 product=await call(context,admin,"POST","/admin/products",{...base,name:"Business sample "+crypto.randomUUID().slice(0,6)});
 privateProduct=await call(context,admin,"POST","/admin/products",{...base,name:"Worker private "+crypto.randomUUID().slice(0,6),allowedGroupIds:[worker.id]});
 menu=await call(context,admin,"POST","/admin/menus",{saleDate:day(),status:"OPEN",postTitle:"Bài mở bán kiểm thử bốn vai trò",postBody:"Sản phẩm và giá theo nhóm khách.",receivingNote:"Nhận tại điểm giao theo lịch trong đơn",items:[product,privateProduct].map(p=>({productId:p.id,availableQty:"6",costPrice:"20000"}))});
 oldVat=await call(context,admin,"GET","/admin/vat");await call(context,admin,"PATCH","/admin/vat",{rate:"8",expectedVersion:oldVat.version});
 await context.close();
});
test.afterAll(async({browser})=>{if(!oldVat)return;const c=await browser.newContext({ignoreHTTPSErrors:true});const a=await login(c,accounts[0]);const v=await call(c,a,"GET","/admin/vat");await call(c,a,"PATCH","/admin/vat",{rate:oldVat.value.rate,expectedVersion:v.version});await c.close();});

test("customer feed respects groups and seller has operational UI without admin privileges",async({browser})=>{
 const customer=await browser.newContext({ignoreHTTPSErrors:true}),shop=await browser.newContext({ignoreHTTPSErrors:true});
 await login(customer,accounts[1]);await login(shop,seller);const cp=await customer.newPage(),sp=await shop.newPage();const errors:string[]=[];cp.on("pageerror",e=>errors.push(e.message));sp.on("pageerror",e=>errors.push(e.message));
 await cp.goto("/");await expect(cp).toHaveURL(origin+"/feed");await expect(cp.getByRole("heading",{name:"Bảng tin cửa hàng"})).toBeVisible();
 const post=cp.locator(".feed-post").filter({hasText:product.name});await expect(post.getByRole('heading',{name:'Bài mở bán kiểm thử bốn vai trò'})).toBeVisible();await expect(post).not.toContainText(privateProduct.name);
 await screenshot(cp,"business-feed");
 await sp.goto("/shop/menus");await expect(sp.getByRole("link",{name:"Nhân viên",exact:true})).toHaveCount(0);await expect(sp.locator('aside.nav a[href^="/admin"]')).toHaveCount(0);
 const row=sp.locator("tr").filter({hasText:menu.id}).first();await row.getByRole("button",{name:"Xem tồn / trạng thái"}).click();await expect(sp.getByRole("region",{name:"Tồn kho và trạng thái sản phẩm"})).toContainText(product.name);
 await row.getByRole("button",{name:"Sửa món / giá / kho"}).click();await expect(sp.getByLabel("Tiêu đề bài trên bảng tin",{exact:true})).toHaveValue("Bài mở bán kiểm thử bốn vai trò");
 await sp.goto("/shop/reports");await expect(sp.getByRole("heading",{name:"Tổng quan",exact:true})).toBeVisible();await expect(sp.locator(".report-shop-filter select")).toHaveCount(0);await sp.goto("/shop/profile");await expect(sp.getByRole("heading",{name:"Hồ sơ cửa hàng"})).toBeVisible();
 await cp.setViewportSize({width:360,height:820});await expect(cp.locator(".feed-post").first()).toBeVisible();expect(await cp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 expect(errors).toEqual([]);await customer.close();await shop.close();
});

test("four roles complete collective COD, VAT, pickup notification, review and cash remittance",async({browser})=>{
 const customer=await browser.newContext({ignoreHTTPSErrors:true}),shop=await browser.newContext({ignoreHTTPSErrors:true}),delivery=await browser.newContext({ignoreHTTPSErrors:true}),admin=await browser.newContext({ignoreHTTPSErrors:true});
 const c=await login(customer,accounts[1]);await login(shop,seller);await login(delivery,courier);const a=await login(admin,accounts[0]);
 const cp=await customer.newPage(),sp=await shop.newPage(),dp=await delivery.newPage(),ap=await admin.newPage();const errors:string[]=[];for(const p of [cp,sp,dp,ap])p.on("pageerror",e=>errors.push(e.message));
 await sp.goto("/shop/orders");await dp.goto("/courier/orders");await cp.goto("/menu");
 const offer=menu.items.find((i:any)=>i.product_id===product.id);const card=cp.locator(`[data-offer-id="${offer.id}"]`);await card.getByRole("button",{name:"Thêm vào giỏ",exact:true}).click();await cp.getByRole("button",{name:"Tiếp tục đặt hàng",exact:true}).click();
 const options=await call(customer,c,"GET","/delivery/options"),policy=options.policies.find((p:any)=>p.method==="COLLECTIVE");await cp.getByLabel("Cách nhận hàng",{exact:true}).selectOption(policy.id);
 await expect(cp.getByRole("option",{name:/payOS.*chưa cấu hình/})).toBeDisabled();await expect(cp.getByText("VAT 8%",{exact:true})).toBeVisible();
 await cp.getByLabel("Tôi đã kiểm tra",{exact:false}).check();await cp.getByRole("button",{name:"Đặt hàng · Chờ duyệt",exact:true}).click();await expect(cp.getByRole("heading",{name:"Đơn của tôi",exact:true})).toBeVisible();
 await sp.getByRole("combobox",{name:"Trạng thái"}).selectOption("PENDING");
 const trigger=sp.locator(".order-queue-row").filter({hasText:product.name}).first().getByRole("button",{name:/Xem đơn/});
 await trigger.click();
 const own=cp.locator(".business-order").filter({hasText:product.name}).first(),row=sp.locator(".order-detail-pane .business-order");await row.getByRole("button",{name:"Duyệt",exact:true}).click();await expect(own.getByText("Đã duyệt",{exact:true})).toBeVisible();
 await row.getByRole("combobox",{name:"Người giao / trao hàng"}).selectOption(courier.id);await row.getByRole("button",{name:"Phân công",exact:true}).click();
 await row.getByRole("button",{name:"Chuẩn bị",exact:true}).click();await row.getByRole("button",{name:"Báo khách đến lấy",exact:true}).click();
 await expect(own.getByText("Sẵn sàng lấy hàng",{exact:true})).toBeVisible();await expect(cp.locator(".message-notice-content")).toContainText("sẵn sàng lấy");
 const assigned=dp.locator(".business-order").filter({hasText:product.name}).first();await expect(assigned).toBeVisible();dp.once("dialog",d=>d.accept());await assigned.getByRole("button",{name:"Xác nhận giao / nhận",exact:true}).click();
 await expect(own.getByText("Đã thanh toán",{exact:true})).toBeVisible();await expect(own.getByText("Đã giao / nhận",{exact:true})).toBeVisible();
 const orders=await call(customer,c,"GET","/orders"),order=orders.find((o:any)=>o.items.some((i:any)=>i.offer_id===offer.id));expect(order.payment_status).toBe("PAID");expect(BigInt(order.total)).toBe(BigInt(order.merchandise_total)+BigInt(order.vat_amount));
 await own.getByText(/Đánh giá sản phẩm \/ người giao/).click();const review=own.locator(".business-review");await review.locator(`input[type="radio"][name="target"][value="${order.items[0].id}"]`).check();await review.getByRole("textbox").fill("Giao đúng lịch, sản phẩm tốt");await review.getByRole("button",{name:"Gửi đánh giá",exact:true}).click();await expect(review).toContainText("5/5 sao");
 await ap.goto("/admin/finance");const cash=ap.locator(".panel.row-heading").filter({hasText:order.id.slice(0,8)});await expect(cash).toBeVisible();ap.once("dialog",d=>d.accept());await cash.getByRole("button",{name:"Xác nhận nhận tiền",exact:true}).click();await expect(cash).toHaveCount(0);
 const report=await call(admin,a,"GET","/shop/finance");expect(report.unremitted.some((e:any)=>e.order_id===order.id)).toBe(false);expect(Number(report.sales.vat)).toBeGreaterThan(0);
 await screenshot(ap,"business-finance");await cp.setViewportSize({width:360,height:820});await screenshot(cp,"business-customer-order-mobile");expect(await cp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 expect(errors).toEqual([]);for(const context of [customer,shop,delivery,admin])await context.close();
});

test("two shop carts stay separate after checkout and sellers can see their balance", async ({ browser }) => {
  const customer = await browser.newContext({ ignoreHTTPSErrors: true });
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  const merchant = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const a = await login(admin, accounts[0]);
    const c = await login(customer, accounts[1]);
    const phone = "+849" + String(crypto.randomInt(10000000, 99999999));
    const password = "MarketplaceBrowser123!";
    const otp = await call(merchant, { csrfToken: "" }, "POST", "/auth/registration/otp", { phone });
    const verified = await call(merchant, { csrfToken: "" }, "POST", "/auth/registration/verify", {
      challengeId: otp.challengeId, code: otp.demoCode,
    });
    await call(merchant, { csrfToken: "" }, "POST", "/auth/register", {
      ticket: verified.ticket, displayName: "Người bán kiểm thử", password,
    });
    const applicant = await login(merchant, { phone, password });
    const shopName = "Cửa hàng kiểm thử " + crypto.randomUUID().slice(0, 6);
    const application = await call(merchant, applicant, "POST", "/marketplace/application", {
      name: shopName, address: "Hà Đông",
    });
    const shop = await call(admin, a, "PATCH", "/admin/shop-applications/" + application.id, {
      approved: true, expectedVersion: application.version,
    });
    const owner = await login(merchant, { phone, password });
    expect(owner.user.shop_id).toBe(shop.shop_id);
    const item = await call(merchant, owner, "POST", "/shop/products", {
      name: "Món của shop thứ hai " + crypto.randomUUID().slice(0, 6),
      categoryId: product.category_id, unitId: product.unit_id, quantityStep: "1", defaultCostPrice: "30000",
    });
    const round = await call(merchant, owner, "POST", "/shop/menus", {
      saleDate: day(), status: "OPEN",
      items: [{ productId: item.id, availableQty: "10", salePrice: "65000" }],
    });
    const sp = await merchant.newPage();
    await sp.goto("/shop/balance");
    await expect(sp.getByRole("heading", { name: "Số dư và rút tiền" })).toBeVisible();
    await expect(sp.getByText("0/2 lượt")).toBeVisible();
    await expect(sp.getByRole("button", { name: "Gửi yêu cầu rút" })).toBeDisabled();

    const cp = await customer.newPage();
    await cp.goto("/menu");
    const firstOffer = menu.items.find((i: any) => i.product_id === product.id);
    await cp.locator('[data-offer-id="' + firstOffer.id + '"]').getByRole("button", { name: "Thêm vào giỏ" }).click();
    await cp.getByRole("button", { name: "Mua tiếp", exact: true }).click();
    await cp.locator('[data-offer-id="' + round.items[0].id + '"]').getByRole("button", { name: "Thêm vào giỏ" }).click();
    const shopSelect = cp.getByLabel("Giỏ hàng của shop");
    await expect(shopSelect).toHaveValue(shop.shop_id);
    await expect(cp.locator(".cart-line")).toHaveCount(1);
    await expect(cp.locator(".cart-line")).toContainText(item.name);
    await cp.getByRole("button", { name: "Tiếp tục đặt hàng", exact: true }).click();
    const options = await call(customer, c, "GET", "/delivery/options?shopId=" + shop.shop_id);
    const pickup = options.policies.find((policy: any) => policy.method === "COLLECTIVE");
    await cp.getByLabel("Cách nhận hàng", { exact: true }).selectOption(pickup.id);
    await cp.getByLabel("Tôi đã kiểm tra", { exact: false }).check();
    await cp.getByRole("button", { name: "Đặt hàng · Chờ duyệt", exact: true }).click();
    await expect(cp).toHaveURL(origin + "/orders");
    await cp.goto("/cart");
    await expect(cp.locator(".cart-line")).toHaveCount(1);
    await expect(cp.locator(".cart-line")).toContainText(product.name);
    await expect(cp.getByLabel("Giỏ hàng của shop")).not.toHaveValue(shop.shop_id);
  } finally {
    await customer.close();
    await admin.close();
    await merchant.close();
  }
});
