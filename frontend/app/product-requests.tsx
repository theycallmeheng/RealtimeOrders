"use client";

import { useState } from "react";
import { BusinessHeading, useLoad, type BusinessProps } from "./business-ui";
import { ShopSelect } from "./marketplace-ui";
import { storefrontShopKey } from "../lib/marketplace";

type Row = Record<string, any>;
const labels: Record<string, string> = { PENDING: "Chờ tiếp nhận", REVIEWING: "Đang xem xét", WAITING: "Chờ mở bán", OPENED: "Đã mở bán", REJECTED: "Từ chối", CANCELLED: "Khách đã hủy" };
const active = ["PENDING", "REVIEWING", "WAITING"];
const time = (v: string) => new Date(v).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" });
const cash = (v: string) => new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(Number(v));

function image(url: string) {
  return url ? <img className="request-image" src={url} alt="Ảnh sản phẩm khách mong muốn" referrerPolicy="no-referrer" onError={e => { e.currentTarget.hidden = true; }} /> : null;
}

export default function ProductRequests(props: BusinessProps) {
  const customer = props.user.role === "CUSTOMER";
  const prefix = customer ? "" : props.user.role === "SELLER" ? "/shop" : "/admin";
  const [status, setStatus] = useState(""), [shop, setShop] = useState(""), [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null), [form, setForm] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [actionError, setActionError] = useState(""), [notice, setNotice] = useState("");
  const query = new URLSearchParams({ offset: String(page * 50) });
  if (status) query.set("status", status);
  if (shop) query.set("shopId", shop);
  const list = useLoad(prefix + "/product-requests?" + query, props);
  const shops = useLoad(props.user.role !== "SELLER" ? "/marketplace/shops" : null, props).data ?? [];
  const detail = useLoad(selected ? prefix + "/product-requests/" + selected : null, props);
  const current = detail.data?.id === selected ? detail.data : null;
  const products = useLoad(!customer && current ? prefix + "/products?shopId=" + current.shop_id : null, props).data ?? [];
  const disabled = busy || !props.online;
  const run = async (path: string, body: Row, method = "POST") => {
    if (disabled) return null;
    setBusy(true); setActionError(""); setNotice("");
    try {
      const row = await props.mutate(path, body, method);
      setSelected(row.id); detail.setData(row); setNotice("Đã lưu yêu cầu sản phẩm.");
      return row;
    } catch (e) { setActionError((e as Error).message); return null; }
    finally { setBusy(false); }
  };
  const openForm = (row: Row = {}) => {
    setForm(row); setActionError(""); setNotice("");
  };
  return <>
    <BusinessHeading title="Yêu cầu sản phẩm" sub={customer
      ? "Gửi nhu cầu tới một shop. Yêu cầu chưa tạo đơn hoặc giữ hàng; bạn tự đặt khi sản phẩm mở bán."
      : "Tiếp nhận nhu cầu, liên kết sản phẩm của shop và thông báo khách khi thực sự mở bán."} />
    <div className="request-toolbar">
      <label>Trạng thái<select value={status} onChange={e => { setStatus(e.target.value); setPage(0); }}>
        <option value="">Tất cả trạng thái</option>{Object.entries(labels).map(([id, name]) => <option value={id} key={id}>{name}</option>)}
      </select></label>
      {props.user.role !== "SELLER" && <ShopSelect shops={shops} value={shop} allLabel="Tất cả shop" onChange={id => { setShop(id); setPage(0); }} />}
      {customer && <button className="primary" disabled={disabled} onClick={() => openForm()}>Gửi yêu cầu sản phẩm</button>}
    </div>
    {(list.error || detail.error || actionError) && <p className="notice error" role="alert">{actionError || detail.error || list.error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {form && <section className="panel request-form" aria-label={form.id ? "Sửa yêu cầu sản phẩm" : "Yêu cầu sản phẩm mới"}>
      <div className="row-heading"><h2>{form.id ? "Sửa yêu cầu" : "Bạn muốn shop bổ sung sản phẩm nào?"}</h2><button disabled={busy} onClick={() => setForm(null)}>Đóng biểu mẫu</button></div>
      <p className="muted">Tối đa 5 yêu cầu/ngày theo giờ Việt Nam trên toàn sàn. Giá mong muốn chỉ để shop tham khảo.</p>
      <form key={form.id || "new"} onSubmit={async e => {
        e.preventDefault(); const data = Object.fromEntries(new FormData(e.currentTarget));
        const row = await run("/product-requests" + (form.id ? "/" + form.id : ""),
          { ...data, ...(form.id ? { expectedVersion: form.version } : {}) }, form.id ? "PATCH" : "POST");
        if (row) setForm(null);
      }}>
        <fieldset disabled={disabled} className="request-fields">
          {!form.id && <label>Shop tiếp nhận<select name="shopId" required defaultValue={shop || (typeof window !== "undefined" ? sessionStorage.getItem(storefrontShopKey(props.user.id)) : "") || ""}>
            <option value="">Chọn shop</option>{shops.map((s: Row) => <option value={s.id} key={s.id}>{s.name}</option>)}
          </select></label>}
          <label>Tên sản phẩm<input name="name" required maxLength={200} defaultValue={form.name} placeholder="Ví dụ: sữa yến mạch không đường" /></label>
          <label className="request-wide">Mô tả mong muốn<textarea name="description" required maxLength={2000} defaultValue={form.description} placeholder="Thương hiệu, quy cách, đặc điểm sản phẩm…" /></label>
          <label>Số lượng mong muốn<input type="number" name="quantity" required min="0.001" max="999999999" step="0.001" defaultValue={form.quantity || "1"} /></label>
          <label>Đơn vị<input name="unit" required maxLength={40} defaultValue={form.unit_label} placeholder="Hộp, chai, kg…" /></label>
          <label>Giá mong muốn / đơn vị (đ, tùy chọn)<input name="desiredPrice" type="number" min="0" max="999999999" step="1" defaultValue={form.desired_price ?? ""} /></label>
          <label>URL ảnh HTTPS (tùy chọn)<input name="imageUrl" type="url" pattern="https://.*" maxLength={2048} defaultValue={form.image_url} /></label>
          <label className="request-wide">Link sản phẩm tham khảo HTTPS (tùy chọn)<input name="referenceUrl" type="url" pattern="https://.*" maxLength={2048} defaultValue={form.reference_url} /></label>
          <div className="request-wide"><button className="primary">{busy ? "Đang gửi…" : form.id ? "Lưu thay đổi yêu cầu" : "Gửi tới shop"}</button></div>
        </fieldset>
      </form>
    </section>}
    <div className="request-layout">
      <section aria-label="Danh sách yêu cầu sản phẩm">
        {!list.data && !list.error && <p role="status">Đang tải yêu cầu…</p>}
        {list.data?.length === 0 && <p className="empty">Chưa có yêu cầu phù hợp.</p>}
        {list.data?.map((row: Row) => <button key={row.id} className={"request-row " + (selected === row.id ? "selected" : "")} aria-pressed={selected === row.id} onClick={() => { setSelected(row.id); setActionError(""); }}>
          <span className="row-heading"><strong>{row.name}</strong><span className={"status " + row.status}>{labels[row.status]}</span></span>
          <span className="muted">{row.shop_name}{!customer && ` · ${row.customer_name}`}</span>
          <span>{Number(row.quantity).toLocaleString("vi-VN")} {row.unit_label} · {time(row.created_at)}</span>
        </button>)}
        <div className="actions"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Trang trước</button><span>Trang {page + 1}</span><button disabled={!list.data || list.data.length < 50} onClick={() => setPage(page + 1)}>Trang sau</button></div>
      </section>
      <section className="panel request-detail" aria-label="Chi tiết yêu cầu sản phẩm">
        {!current ? <p className="muted">Chọn yêu cầu để xem nội dung và tiến trình.</p> : <>
          <div className="row-heading"><h2>{current.name}</h2><span className={"status " + current.status}>{labels[current.status]}</span></div>
          <p className="muted">{current.shop_name} · {current.customer_name}</p>
          <p className="request-description">{current.description}</p>
          <p><strong>Nhu cầu:</strong> {Number(current.quantity).toLocaleString("vi-VN")} {current.unit_label}</p>
          {current.desired_price !== null && <p><strong>Giá mong muốn:</strong> {cash(current.desired_price)} / {current.unit_label}</p>}
          {image(current.image_url)}
          {current.reference_url && <p><a href={current.reference_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Xem sản phẩm tham khảo ↗</a></p>}
          {current.decision_note && <p className="notice"><strong>Phản hồi của shop:</strong> {current.decision_note}</p>}
          {customer && <div className="actions">
            {current.status === "PENDING" && <button disabled={disabled} onClick={() => openForm(current)}>Sửa yêu cầu</button>}
            {active.includes(current.status) && <button disabled={disabled} onClick={() => {
              if (window.confirm("Hủy yêu cầu sản phẩm này?")) void run("/product-requests/" + current.id + "/cancel", { expectedVersion: current.version });
            }}>Hủy yêu cầu</button>}
            {current.status === "OPENED" && <button className="primary" onClick={() => { sessionStorage.setItem(storefrontShopKey(props.user.id), current.shop_id); props.navigate("catalog"); }}>Xem hàng của shop</button>}
          </div>}
          {!customer && active.includes(current.status) && <form key={current.id + ":" + current.version} onSubmit={e => {
            e.preventDefault(); const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement;
            const data = Object.fromEntries(new FormData(e.currentTarget)); const target = submitter.value;
            if (target === "REJECTED" && !String(data.note).trim()) { setActionError("Nhập lý do từ chối."); return; }
            if (target === "WAITING" && !data.productId) { setActionError("Chọn sản phẩm của shop để liên kết."); return; }
            void run(prefix + "/product-requests/" + current.id, { ...data, status: target, expectedVersion: current.version }, "PATCH");
          }}>
            <fieldset disabled={disabled} className="request-review">
              {current.status !== "PENDING" && <label>Sản phẩm liên kết<select name="productId" defaultValue={current.product_id || ""}>
                <option value="">Chọn sản phẩm của shop</option>{products.filter((p: Row) => p.shop_id === current.shop_id && p.active && !p.deleted_at).map((p: Row) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
              </select></label>}
              <label>Phản hồi / lý do từ chối<textarea name="note" maxLength={1000} defaultValue={current.decision_note} /></label>
              <div className="actions">
                {current.status === "PENDING" ? <button className="primary" value="REVIEWING">Tiếp nhận xem xét</button> : <button className="primary" value="WAITING">{current.status === "WAITING" ? "Cập nhật sản phẩm liên kết" : "Xác nhận chờ mở bán"}</button>}
                <button value="REJECTED">Từ chối yêu cầu</button>
              </div>
            </fieldset>
            {current.status !== "PENDING" && <p className="muted">Chưa có sản phẩm? <button type="button" className="ghost small" onClick={() => props.navigate("products")}>Đến sản phẩm của shop</button>. Sau khi liên kết, mở bán trong menu; hệ thống tự thông báo khi khách có thể mua.</p>}
          </form>}
          <h3>Tiến trình yêu cầu</h3>
          <ol className="request-history">{current.history.map((h: Row, i: number) => <li key={i}><strong>{labels[h.status]}</strong><time>{time(h.at)}</time>{h.note && <p>{h.note}</p>}</li>)}</ol>
        </>}
      </section>
    </div>
  </>;
}
