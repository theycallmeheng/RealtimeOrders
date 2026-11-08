"use client";
import React, { useEffect, useRef, useState } from "react";
import PayosCheckout from "./payos-checkout";
import { storefrontShopKey } from "../lib/marketplace";

type Row = Record<string, any>;
export type BusinessProps = { kind: string; user: Row; online: boolean; refresh: number; request: (path: string) => Promise<any>; mutate: (path: string, body: Row, method?: string) => Promise<any>; navigate: (tab: string) => void };
const cash = (n: any) => new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(Number(n ?? 0));
const time = (n: string) => n ? new Date(n).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "—";
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" });
const names: Row = { OPEN:"Đang mở bán", SOLD_OUT:"Đã bán hết", SCHEDULED:"Chờ giờ mở", EXPIRED:"Đã hết hạn", CLOSED:"Đã đóng", PENDING:"Chờ duyệt", APPROVED:"Đã duyệt", PREPARING:"Đang chuẩn bị", SHIPPING:"Đang giao", READY_FOR_PICKUP:"Sẵn sàng lấy hàng", DELIVERY_FAILED:"Giao chưa thành công", DELIVERED:"Đã giao / nhận", CANCELLED:"Đã hủy", REJECTED:"Từ chối", UNPAID:"Chưa thu đủ", PAID:"Đã thanh toán", LEGACY:"Chưa có dữ liệu thanh toán", REFUND_PENDING:"Chờ hoàn tiền", REFUNDED:"Đã hoàn tiền", CUSTOMER:"Khách hàng", SELLER:"Người bán", SHIPPER:"Người giao hàng", ADMIN:"Người quản trị" };
function latestOrder(previous: Row | null | undefined, incoming: Row) {
  return previous && previous.id === incoming.id && previous.version && incoming.version &&
    BigInt(previous.version) > BigInt(incoming.version) ? previous : incoming;
}

export function useLoad(path: string | null, props: BusinessProps) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const previousPath = useRef(path);
  useEffect(() => {
    let live = true;
    if (previousPath.current !== path) {
      setData((old: Row | null) => old?.id && path === "/orders/" + old.id ? old : null);
      previousPath.current = path;
    }
    setError("");
    if (!path) return;
    props.request(path).then((next) => {
      if (!live) return;
      setData((old: any) => {
        if (Array.isArray(next) && Array.isArray(old)) {
          return next.map((row: Row) => latestOrder(old.find((item: Row) => item.id === row.id), row));
        }
        return next?.id ? latestOrder(old, next) : next;
      });
    }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [path, props.refresh]);
  return { data, error, setData };
}
const Badge = ({ value }: { value: string }) => <span className={"status " + value}>{names[value] ?? value}</span>;

export function BusinessHeading({ title, sub }: { title:string; sub?:string }) {
  return <header className="page-heading business-heading"><div><div className="eyebrow">Cửa hàng · RealtimeOrders</div><h1>{title}</h1>{sub&&<p>{sub}</p>}</div></header>;
}

export default function BusinessScreen(props: BusinessProps) {
  if (props.kind === "orders") return <BusinessOrders {...props} />;
  if (props.kind === "feed") return <Feed {...props} />;
  if (props.kind === "shop") return <ShopProfile {...props} />;
  if (props.kind === "staff") return <Staff {...props} />;
  if (props.kind === "finance") return <Finance {...props} />;
  if (props.kind === "reviews") return <ReviewManagement {...props} />;
  return null;
}

function BusinessOrders(props: BusinessProps) {
  const isShop = ["ADMIN", "SELLER"].includes(props.user.role), isCourier = props.user.role === "SHIPPER";
  const prefix = isShop ? "/shop" : isCourier ? "/courier" : "";
  const [page, setPage] = useState(0), [filter, setFilter] = useState(""), [shopId, setShopId] = useState("");
  const shops = useLoad(props.user.role === "ADMIN" ? "/marketplace/shops" : null, props).data;
  const { data, error, setData } = useLoad(prefix + "/orders?page=" + page + (filter ? "&status=" + filter : "") +
    (shopId ? "&shopId=" + shopId : ""), props);
  const staff = useLoad(isShop ? "/shop/staff" : null, props).data;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const changeShop = (id: string) => {
    setShopId(id);
    setSelectedId(null);
    setPage(0);
  };
  const detail = useLoad(selectedId ? "/orders/" + selectedId : null, props);
  const orders: Row[] = data?.filter((order: Row) => !filter || order.status === filter) ?? [];
  const selectedInList = data?.find((order: Row) => order.id === selectedId);
  const selected = detail.data?.id === selectedId && detail.data
    ? selectedInList ? latestOrder(detail.data, selectedInList) : detail.data
    : selectedInList;
  const detailRef = useRef<HTMLElement>(null);
  const detailTrigger = useRef<HTMLButtonElement>(null);
  const filterRef = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (selectedId) detailRef.current?.focus();
  }, [selectedId]);
  const closeDetail = () => {
    setSelectedId(null);
    (detailTrigger.current?.isConnected ? detailTrigger.current : filterRef.current)?.focus();
  };
  const [payment, setPayment] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [dialog, setDialog] = useState<Row | null>(null);
  const dialogRef=useRef<HTMLElement>(null);
  useEffect(()=>{
    if(!dialog)return;
    const old=document.activeElement as HTMLElement, root=dialogRef.current;
    const controls=()=>Array.from(root?.querySelectorAll<HTMLElement>('button:not([disabled]),input,textarea,select')??[]);
    controls()[0]?.focus();
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();setDialog(null);}if(e.key==='Tab'){const all=controls();if(e.shiftKey&&document.activeElement===all[0]){e.preventDefault();all.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===all.at(-1)){e.preventDefault();all[0]?.focus();}}};
    document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);old?.focus();};
  },[!!dialog]);
  const run = async (path: string, body: Row) => {
    setBusy(true);
    setMessage("");
    try {
      const result = await props.mutate(path, body);
      if (Array.isArray(result?.items)) {
        setData((old: Row[] | null) => old?.map((order) => order.id === result.id ? latestOrder(order, result) : order) ?? old);
        detail.setData((old: Row | null) => old?.id === result.id ? latestOrder(old, result) : old);
      }
      setDialog(null);
      return result;
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const act = (o: Row, action: string, body: Row = {}) => run(prefix + "/orders/" + o.id + "/" + action, { expectedVersion:o.version, ...body });
  const reason = (o: Row, action: string, title: string, body: Row = {}) => setDialog({ title, path:prefix + "/orders/" + o.id + "/" + action, body:{ expectedVersion:o.version, ...body } });
  const renderOrder = (o: Row) => (
    <article className="panel business-order" key={o.id}>
      <div className="row-heading order-card-heading"><div><strong>Đơn #{o.id.slice(0,8).toUpperCase()}</strong><div className="muted">{time(o.created_at)}</div></div><Badge value={o.status} /></div>
      <div className="business-lines">{o.items.map((i: Row) => <div key={i.id}><span>{i.product_name_snapshot} × {Number(i.quantity)} {i.unit_snapshot}</span><strong>{cash(i.line_total)}</strong></div>)}</div>
      <div className="business-totals"><span>Tiền hàng: {cash(o.merchandise_total)}</span><span>VAT {Number(o.vat_rate)}%: {cash(o.vat_amount)}</span><span>Phí giao: {cash(o.shipping_fee)}</span><strong>Tổng: {cash(o.total)}</strong></div>
      <p className="order-payment"><strong>{o.payment_method === "PAYOS" ? "payOS VietQR" : o.payment_method === "COD" ? "COD khi nhận" : "Đơn lịch sử"}</strong> · <Badge value={o.payment_status} /></p>
      {o.payment?.tracked && <p className="muted">Đã thu: {cash(o.payment.received)} · Đã hoàn: {cash(o.payment.refunded)} · Còn phải trả: {cash(o.payment.remaining)}</p>}
      {o.payment_method === "PAYOS" && o.status === "APPROVED" && o.payment_status === "UNPAID" && <p>Thanh toán trước {time(o.payment_deadline)}. Chưa thanh toán đủ thì chưa chuẩn bị hàng.</p>}
      <details><summary>Địa chỉ, giao nhận và lịch sử</summary><p>{o.address_snapshot.recipient_name} · {o.address_snapshot.phone_e164}</p>
        {o.delivery_method === "COLLECTIVE" ? <p>Nhận tập trung: {o.delivery_snapshot.pickupSlot?.address_line} · {time(o.delivery_snapshot.pickupSlot?.starts_at)} → {time(o.delivery_snapshot.pickupSlot?.ends_at)}</p> : <p>{o.address_snapshot.address_line}</p>}
        {o.courier_id && <p>Người giao: {staff?.find?.((x: Row) => x.id === o.courier_id)?.display_name ?? o.courier_id}</p>}
        {o.note && <p>Ghi chú: {o.note}</p>}
        <ol>{o.history.map((h: Row)=><li key={h.id}>{time(h.created_at)} · {names[h.to_status] ?? h.to_status}{h.reason ? " · " + h.reason : ""}</li>)}</ol>
      </details>
      {isShop && ["APPROVED","PREPARING","READY_FOR_PICKUP","DELIVERY_FAILED"].includes(o.status) && <form className="business-assign" onSubmit={e=>{e.preventDefault(); const id=new FormData(e.currentTarget).get("courierId"); if(id) act(o,"assign",{courierId:id});}}>
        <label>Người giao / trao hàng <select key={o.courier_id ?? "none"} name="courierId" defaultValue={o.courier_id ?? ""} required><option value="">Chọn nhân viên</option>{staff?.filter?.((p: Row)=>p.role==="SHIPPER" && p.status==="ACTIVE").map((p: Row)=><option key={p.id} value={p.id}>{p.display_name}</option>)}</select></label><button disabled={!props.online || busy}>Phân công</button>
      </form>}
      <div className="actions business-actions">
        {isShop && o.status==="PENDING" && <><button className="primary" disabled={!props.online||busy} onClick={()=>act(o,"approve")}>Duyệt</button><button disabled={!props.online||busy} onClick={()=>reason(o,"reject","Từ chối đơn")}>Từ chối</button></>}
        {isShop && o.cancellation_requests.some((c: Row)=>c.state==="OPEN") && <><button disabled={!props.online||busy} onClick={()=>reason(o,"decide-cancel","Chấp thuận hủy và hoàn kho",{accept:true})}>Chấp thuận hủy</button><button disabled={!props.online||busy} onClick={()=>reason(o,"decide-cancel","Không chấp thuận hủy",{accept:false})}>Không chấp thuận hủy</button></>}
        {isShop && o.status==="APPROVED" && <button disabled={!props.online||busy||(o.payment_method==="PAYOS" && Number(o.payment?.remaining)>0)} onClick={()=>act(o,"transition",{status:"PREPARING"})}>Chuẩn bị</button>}
        {isShop && o.status==="PREPARING" && <button disabled={!props.online||busy||!o.courier_id} onClick={()=>act(o,"transition",{status:o.delivery_method==="COLLECTIVE"?"READY_FOR_PICKUP":"SHIPPING"})}>{o.delivery_method==="COLLECTIVE"?"Báo khách đến lấy":"Bàn giao vận chuyển"}</button>}
        {(isShop||isCourier) && ["SHIPPING","READY_FOR_PICKUP"].includes(o.status) && <><button className="primary" disabled={!props.online||busy} onClick={()=>{if(window.confirm(o.payment_method==="COD"?`Xác nhận đã giao hàng và thu đủ ${cash(o.total)}?`:"Xác nhận đã bàn giao đủ hàng cho khách?"))act(o,"transition",{status:"DELIVERED",codAmount:o.total});}}>Xác nhận giao / nhận</button><button disabled={!props.online||busy} onClick={()=>reason(o,"delivery-failed","Ghi nhận giao không thành công")}>Giao chưa thành công</button></>}
        {isShop && o.status==="DELIVERY_FAILED" && <><button disabled={!props.online||busy} onClick={()=>act(o,"retry-delivery")}>Giao lại</button><button disabled={!props.online||busy} onClick={()=>reason(o,"confirm-return","Xác nhận đã nhận đủ hàng hoàn",{received:true})}>Nhận hàng hoàn và hủy</button></>}
        {!isShop&&!isCourier&&o.status==="PENDING"&&<button disabled={!props.online||busy} onClick={()=>reason(o,"cancel","Hủy đơn chờ")}>Hủy đơn</button>}
        {!isShop&&!isCourier&&["APPROVED","PREPARING","READY_FOR_PICKUP"].includes(o.status)&&!o.cancellation_requests.some((c:Row)=>c.state==="OPEN")&&<button disabled={!props.online||busy} onClick={()=>reason(o,"cancellation-requests","Gửi yêu cầu hủy")}>Yêu cầu hủy</button>}
        {!isShop&&!isCourier&&o.status==="APPROVED"&&o.payment_method==="PAYOS"&&o.payment_status==="UNPAID"&&<button className="primary" disabled={!props.online||busy} onClick={async()=>{const p=await run("/orders/"+o.id+"/payment-link",{});if(p?.checkout_url)setPayment(p);}}>Quét QR thanh toán</button>}
      </div>
      {!isShop&&!isCourier&&o.status==="DELIVERED"&&<OrderReview order={o} {...props} />}
    </article>
  );
  return <>
    <BusinessHeading title={isShop ? "Xử lý đơn hàng" : isCourier ? "Đơn được phân công" : "Đơn của tôi"} sub={isShop ? "Theo dõi, duyệt đơn và điều phối giao nhận trong một nơi." : isCourier ? "Các đơn được giao cho bạn, cùng thông tin nhận hàng và thu tiền." : "Theo dõi tiến trình giao nhận, thanh toán và đánh giá đơn hàng."} />
    <p className="order-help">Đơn được giữ hàng sau khi duyệt. Thanh toán online sau khi duyệt hoặc trả COD khi nhận hàng.</p>
    <div className={isShop ? "order-queue-toolbar" : "toolbar"}>{props.user.role === "ADMIN" && <label>Cửa hàng
          <select value={shopId} onChange={(e) => changeShop(e.target.value)}>
            <option value="">Tất cả shop</option>
            {shops?.map((store: Row) => <option key={store.id} value={store.id}>{store.name}</option>)}
          </select>
        </label>}
        <label>Trạng thái <select ref={filterRef} value={filter} onChange={e => { setFilter(e.target.value); setPage(0); setSelectedId(null); }}><option value="">Tất cả</option>{["PENDING","APPROVED","PREPARING","SHIPPING","READY_FOR_PICKUP","DELIVERY_FAILED","DELIVERED","CANCELLED","REJECTED"].map(s=><option key={s} value={s}>{names[s]}</option>)}</select></label>{isShop && data && <span className="muted">{orders.length} đơn trên trang</span>}</div>
    {(error || (!selectedId && message)) && <p className="notice warn" role="alert">{error || message}</p>}
    {!data && !error && <p>Đang tải đơn…</p>}
    {isShop ? (
      <div className={"order-queue" + (selectedId ? " has-detail" : "")}>
        <section className="panel order-queue-list" aria-label="Danh sách đơn hàng">
          <div className="table-scroll order-queue-scroll">
            <table className="order-queue-table">
              <thead><tr><th scope="col">Đơn hàng</th><th scope="col">Người nhận</th><th scope="col">Trạng thái</th><th scope="col">Tổng tiền</th><th scope="col">Thao tác</th></tr></thead>
              <tbody>{orders.map((order) => {
                const code = order.id.slice(0, 8).toUpperCase();
                return (
                  <tr className="order-queue-row" data-order-id={order.id} data-selected={selectedId === order.id} key={order.id}>
                    <td className="order-queue-code"><strong>#{code}</strong>{props.user.role === "ADMIN" && <small>{order.shop_name_snapshot}</small>}<small>{time(order.created_at)}</small><small>{order.items[0]?.product_name_snapshot}{order.items.length > 1 ? ` và ${order.items.length - 1} món khác` : ""}</small></td>
                    <td data-label="Người nhận"><strong>{order.address_snapshot?.recipient_name || "—"}</strong><small>{order.delivery_method === "COLLECTIVE" ? "Nhận tập trung" : "Giao riêng"}</small></td>
                    <td data-label="Trạng thái"><Badge value={order.status} /></td>
                    <td data-label="Tổng tiền" className="money">{cash(order.total)}</td>
                    <td><button className="small" type="button" aria-label={`Xem đơn #${code}`} aria-expanded={selectedId === order.id} aria-controls={selectedId === order.id ? "order-queue-detail" : undefined} onClick={(e) => {
                      detailTrigger.current = e.currentTarget;
                      setMessage("");
                      detail.setData(order);
                      setSelectedId(order.id);
                    }}>Chi tiết</button></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          {data && !orders.length && <p className="empty">Không có đơn phù hợp với trạng thái đã chọn.</p>}
          <div className="order-queue-pages">
            <span className="muted">Trang {page + 1}</span>
            <button type="button" className="small" disabled={!page} onClick={() => setPage(page - 1)}>Trang trước</button>
            <button type="button" className="small" disabled={!data || data.length < 50} onClick={() => setPage(page + 1)}>Trang sau</button>
          </div>
        </section>
        {selectedId && (
          <section id="order-queue-detail" className="panel order-detail-pane" aria-labelledby="order-detail-heading" tabIndex={-1} ref={detailRef}>
            <header className="panel-head"><h2 id="order-detail-heading">Chi tiết đơn</h2><button type="button" className="small" onClick={closeDetail}>Đóng chi tiết</button></header>
            {(detail.error || message) && <p className="notice warn" role="alert">{detail.error || message}</p>}
            {selected ? renderOrder(selected) : <p className="spinner">Đang tải chi tiết đơn…</p>}
          </section>
        )}
      </div>
    ) : <>
      {orders.map(renderOrder)}
      {data?.length === 0 && <p className="empty">Chưa có đơn hàng.</p>}
      {!isCourier && <div className="toolbar"><button disabled={!page} onClick={() => setPage(page - 1)}>Trang trước</button><button disabled={!data || data.length < 50} onClick={() => setPage(page + 1)}>Trang sau</button></div>}
    </>}
    {payment&&<PayosCheckout payment={payment} request={props.request} refresh={props.refresh} close={()=>setPayment(null)} />}
    {dialog&&<div className="business-scrim"><section ref={dialogRef} className="business-dialog" role="dialog" aria-modal="true" aria-label={dialog.title}><h2>{dialog.title}</h2><form onSubmit={e=>{e.preventDefault();run(dialog.path,{...dialog.body,reason:new FormData(e.currentTarget).get("reason")});}}><label>Lý do / ghi chú<textarea name="reason" maxLength={500} required autoFocus /></label><div className="actions"><button className="primary" disabled={busy||!props.online}>Xác nhận</button><button type="button" disabled={busy} onClick={()=>setDialog(null)}>Đóng</button></div></form></section></div>}
  </>;
}

function OrderReview({order,...props}: BusinessProps & {order:Row}) {
  const {data}=useLoad("/reviews/order/"+order.id,props);const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const options=order.items.filter((i:Row)=>!data?.some((r:Row)=>r.target_key==="item:"+i.id));
  const courier=order.courier_id&&!data?.some((r:Row)=>r.courier_id===order.courier_id);
  return <details className="business-review"><summary>Đánh giá sản phẩm / người giao ({data?.length??0})</summary>
    {data?.map((r:Row)=><p key={r.id}>{r.rating}/5 sao · {r.comment || "Không có nhận xét"}{r.hidden&&" · Nội dung đã được ẩn"}</p>)}
    {(options.length>0||courier)&&<form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget),target=f.get("target");setBusy(true);try{await props.mutate("/reviews",{orderId:order.id,target:target==="COURIER"?"COURIER":"PRODUCT",itemId:target,rating:f.get("rating"),comment:f.get("comment")});setError("");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>
      <fieldset className="review-options"><legend>Chọn nội dung đánh giá</legend><div className="review-options-list">{options.map((i:Row,index:number)=><label className="review-choice" key={i.id}><input type="radio" name="target" value={i.id} defaultChecked={index===0} required />{i.product_name_snapshot}</label>)}{courier&&<label className="review-choice"><input type="radio" name="target" value="COURIER" defaultChecked={options.length===0} required />Người giao / trao hàng</label>}</div></fieldset>
      <fieldset className="review-options"><legend>Số sao</legend><div className="review-options-list">{[1,2,3,4,5].map(n=><label className="review-choice" key={n}><input type="radio" name="rating" value={n} defaultChecked={n===5} required />{n} sao</label>)}</div></fieldset><label>Nhận xét<textarea name="comment" maxLength={1000}/></label>
      <button disabled={!props.online||busy}>Gửi đánh giá</button>{error&&<p role="alert">{error}</p>}
    </form>}
  </details>;
}

function Feed(props: BusinessProps) {
  const {data,error}=useLoad("/feed",props);
  if(error)return <p className="notice error" role="alert">{error}</p>;
  if(!data)return <p className="spinner" role="status">Đang tải bảng tin…</p>;
  const openCatalog = (shopId: string) => {
    sessionStorage.setItem(storefrontShopKey(props.user.id), shopId);
    props.navigate("catalog");
  };
  const image=(o:Row)=>{const item=o.images?.[0];if(!item)return "";if(typeof item==="string")return /^(https:\/\/|\/)/.test(item)?item:"/api/v1/media/"+encodeURIComponent(item);return item.source_url||item.url||(item.asset_id?"/api/v1/media/"+encodeURIComponent(item.asset_id):"");};
  return <>
    <BusinessHeading title="Bảng tin cửa hàng" sub={"Chào "+props.user.display_name+", cùng xem cửa hàng có gì hôm nay nhé."} />
    <section aria-labelledby="market-shops-title" className="market-shops">
      <div className="feed-section-heading"><h2 id="market-shops-title">Cửa hàng trên sàn</h2>
        <button onClick={() => openCatalog("")}>Xem hàng trong ngày</button>
      </div>
      <div className="market-finance-grid">
        {(data.shops as Row[]).map((shop) => <article className="panel market-record market-store" key={shop.id}>
          <img src={shop.logoUrl || "/grocery-basket.svg"} alt="" loading="lazy" />
          <div><h3>{shop.name}</h3><p>{shop.description || shop.address}</p>
            <button onClick={() => openCatalog(shop.id)}>Xem sản phẩm</button>
          </div>
        </article>)}
      </div>
    </section>
    <div className="feed-section-heading"><div><h2>Thông tin mở bán</h2><p className="muted">Các đợt bán dành cho nhóm khách hàng của bạn.</p></div><span className="feed-post-count">{data.posts.length} đợt</span></div>
    <div className="feed-posts">{data.posts.map((post:Row)=><article key={post.id} className="panel feed-post">
      <header className="feed-post-heading"><div><span className="eyebrow">{post.shop.name} · {post.sale_date.split("-").reverse().join("/")}</span><h2>{post.post_title||"Menu ngày "+post.sale_date}</h2></div><Badge value={post.effective_status||post.status} /></header>
      <p className="feed-schedule">{time(post.opens_at)} → {time(post.closes_at)}</p>
      {post.post_image_url&&<img className="feed-image" src={post.post_image_url} alt={post.post_title||"Đợt bán"}/>}
      {post.post_body&&<p className="business-text">{post.post_body}</p>}
      <ul className="feed-offers">{post.offers.map((o:Row)=><li key={o.id}>
        <div className="feed-product-thumb">{image(o)?<img src={image(o)} alt="" loading="lazy" onError={e=>{e.currentTarget.style.visibility="hidden";}}/>:<span aria-hidden="true">↗</span>}</div>
        <div><strong>{o.name}</strong><small>Còn {Number(o.available_qty)} {o.unit}</small></div><span>{cash(o.unit_price)}<small> / {o.unit}</small></span>
      </li>)}</ul>
      {post.receiving_note&&<p className="feed-pickup"><strong>Lịch nhận hàng:</strong> {post.receiving_note}</p>}
      <footer className="feed-post-footer"><span className="muted">{post.offers.length} sản phẩm</span><button onClick={() => openCatalog(post.shop.id)}>Chọn sản phẩm <span aria-hidden="true">→</span></button></footer>
    </article>)}</div>
    {!data.posts.length&&<div className="empty feed-empty"><span className="empty-symbol" aria-hidden="true">☷</span><h2>Chưa có bài mở bán dành cho nhóm của bạn.</h2><p>Bạn vẫn có thể xem các mặt hàng sắp bán và đăng ký nhận thông báo.</p><button onClick={() => openCatalog("")}>Khám phá sản phẩm</button></div>}
  </>;
}

function ShopProfile(props: BusinessProps) {
  const {data,error}=useLoad("/shop/profile",props);const [form,setForm]=useState<Row|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  useEffect(()=>{if(data)setForm(data.value);},[data]);
  return <><BusinessHeading title="Hồ sơ cửa hàng" sub="Thông tin giới thiệu và liên hệ hiển thị tới khách hàng. Đây là thông tin tự khai của cửa hàng." />{error&&<p role="alert">{error}</p>}
    {form&&<form className="panel form-grid" onSubmit={async e=>{e.preventDefault();setBusy(true);try{await props.mutate("/shop/profile",{...form,expectedVersion:data.version},"PATCH");setMessage("Đã lưu hồ sơ");}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}}}>
      {Object.entries({name:"Tên cửa hàng",description:"Giới thiệu / dịch vụ",address:"Địa chỉ",phone:"Liên hệ",taxCode:"Mã số thuế (nếu có)",registrationNumber:"Số đăng ký kinh doanh (nếu có)",logoUrl:"URL logo HTTPS",coverUrl:"URL ảnh bìa HTTPS"}).map(([key,label])=><label key={key}>{label}{key==="description"?<textarea value={form[key]} maxLength={2000} onChange={e=>setForm({...form,[key]:e.target.value})}/>:<input type={key.endsWith("Url")?"url":"text"} required={key==="name"} value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/>}</label>)}
      <label>Loại hình<select value={form.businessType} onChange={e=>setForm({...form,businessType:e.target.value})}><option value="INDIVIDUAL">Cá nhân</option><option value="HOUSEHOLD">Hộ kinh doanh</option><option value="COMPANY">Doanh nghiệp</option></select></label>
      <div><button className="primary" disabled={busy||!props.online}>Lưu hồ sơ shop</button><p role="status">{message}</p></div>
    </form>}
  </>;
}

function Staff(props:BusinessProps) {
  const shops = useLoad("/marketplace/shops", props).data;
  const {data,error}=useLoad("/admin/staff",props);const [busy,setBusy]=useState(false),[message,setMessage]=useState("");
  return <><BusinessHeading title="Nhân viên cửa hàng" sub="Tạo tài khoản người bán, người giao hàng và quản lý quyền truy cập." />{error&&<p role="alert">{error}</p>}
    <form className="panel form-grid" onSubmit={async e=>{e.preventDefault();const form=e.currentTarget,f=new FormData(form);setBusy(true);try{await props.mutate("/admin/staff",Object.fromEntries(f));form.reset();setMessage("Đã tạo nhân viên");}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}}}>
      <label>Họ tên<input name="name" required maxLength={100}/></label><label>Số điện thoại<input name="phone" type="tel" required/></label><label>Mật khẩu ban đầu<input name="password" type="password" required minLength={10} autoComplete="new-password"/></label><label>Vai trò<select name="role"><option value="SELLER">Người bán</option><option value="SHIPPER">Người giao hàng</option></select></label>
      <label>Shop của người bán<select name="shopId">{shops?.map((store: Row) =>
        <option key={store.id} value={store.id}>{store.name}</option>)}</select></label>
      <button disabled={!props.online||busy}>Tạo nhân viên</button><p role="status">{message}</p>
    </form>
    <div className="panel table-scroll"><table><thead><tr><th>Nhân viên</th><th>Vai trò</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{data?.map((p:Row)=><tr key={p.id}><td>{p.display_name}<div className="muted">{p.phone_e164}</div></td><td>{names[p.role]}</td><td>{p.status}</td><td><button disabled={!props.online||busy} onClick={async()=>{setBusy(true);try{await props.mutate("/admin/users/"+p.id,{expectedVersion:p.version,status:p.status==="ACTIVE"?"LOCKED":"ACTIVE"},"PATCH");}finally{setBusy(false);}}}>{p.status==="ACTIVE"?"Khóa":"Mở khóa"}</button></td></tr>)}</tbody></table></div>
  </>;
}

function Finance(props:BusinessProps) {
  const [from,setFrom]=useState(today()),[to,setTo]=useState(today()),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const {data,error}=useLoad("/shop/finance?from="+from+"&to="+to,props);
  const policy=useLoad(props.user.role==="ADMIN"?"/admin/vat":"/checkout/config",props).data;
  const [rate,setRate]=useState("");useEffect(()=>{if(policy?.value)setRate(String(policy.value.rate));},[policy]);
  const run=async(path:string,body:Row,method="POST")=>{setBusy(true);try{await props.mutate(path,body,method);setMessage("Đã ghi nhận");}catch(e){setMessage((e as Error).message);}finally{setBusy(false);}};
  return <><BusinessHeading title="Thu, hoàn tiền và đối soát COD" sub="Theo dõi dòng tiền, hoàn tiền và bàn giao COD. Doanh thu, VAT và phí giao được tách riêng." />
    <div className="toolbar"><label>Từ ngày<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>Đến ngày<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label></div>
    {(error||message)&&<p role="status">{error||message}</p>}
    {props.user.role==="ADMIN"&&policy&&<form className="panel business-assign" onSubmit={e=>{e.preventDefault();run("/admin/vat",{rate,expectedVersion:policy.version},"PATCH");}}><label>VAT cộng trên tiền hàng (%)<input type="number" min="0" max="100" step="0.01" value={rate} onChange={e=>setRate(e.target.value)} required/></label><button disabled={!props.online||busy}>Lưu thuế suất cho đơn mới</button></form>}
    {data&&<><div className="business-metrics"><div>Tiền đã thu<strong>{cash(data.received)}</strong></div><div>Đã hoàn<strong>{cash(data.refunded)}</strong></div><div>Thu trừ hoàn<strong>{cash(data.netCash)}</strong></div><div>COD chưa bàn giao (mọi ngày)<strong>{cash(data.courierHolding)}</strong></div></div>
      <div className="business-metrics"><div>Doanh thu hàng đã giao<strong>{cash(data.sales.merchandise)}</strong></div><div>VAT đơn đã giao<strong>{cash(data.sales.vat)}</strong></div><div>Giá vốn<strong>{data.sales.cost===null?"Chưa đủ dữ liệu":cash(data.sales.cost)}</strong></div><div>Lãi gộp<strong>{data.sales.grossProfit===null?"Chưa đủ dữ liệu":cash(data.sales.grossProfit)}</strong></div><div>Phí giao đơn đã giao<strong>{cash(data.sales.shipping)}</strong></div></div>
      {data.sales.legacyPaymentOrders>0&&<p className="notice warn">Có {data.sales.legacyPaymentOrders} đơn lịch sử đã giao chưa có dữ liệu thanh toán. Không tự tính chúng thành đã thu hoặc công nợ.</p>}
      <p className="muted">Các danh sách dưới đây hiển thị tối đa {data.listLimit} bản ghi; tổng tiền được tính trên toàn bộ dữ liệu phù hợp.</p>
      <h2>Yêu cầu hoàn tiền</h2>{data.refunds.length===0&&<p>Không có yêu cầu đang chờ.</p>}{data.refunds.map((r:Row)=><form className="panel business-assign" key={r.id} onSubmit={e=>{e.preventDefault();if(!window.confirm("Đã chuyển khoản thực tế đúng số tiền này?"))return;const f=new FormData(e.currentTarget);run("/admin/refunds/"+r.id+"/confirm",{amount:r.amount,reference:f.get("reference"),note:f.get("note")});}}><span>Đơn #{r.order_id.slice(0,8)} · <strong>{cash(r.amount)}</strong></span>{props.user.role==="ADMIN"?<><label>Mã tham chiếu hoàn<input name="reference" required maxLength={100}/></label><label>Ghi chú<input name="note" maxLength={500}/></label><button disabled={busy||!props.online}>Xác nhận đã hoàn</button></>:<span>Chờ quản trị đối soát</span>}</form>)}
      <h2>Tiền COD nhân viên chưa bàn giao</h2>{data.unremitted.map((e:Row)=><div className="panel row-heading" key={e.id}><span>Đơn #{e.order_id.slice(0,8)} · {cash(e.amount)}<small className="muted"> · {e.collector_name}</small></span><button disabled={busy||!props.online} onClick={()=>{if(window.confirm("Xác nhận shop đã thực nhận đủ tiền COD này?"))run("/shop/money/"+e.id+"/remit",{received:true});}}>Xác nhận nhận tiền</button></div>)}
      <h2>Lịch sử thu / hoàn trong khoảng ngày</h2><div className="panel table-scroll"><table><thead><tr><th>Thời gian</th><th>Đơn</th><th>Loại</th><th>Kênh</th><th>Số tiền</th><th>Tham chiếu</th></tr></thead><tbody>{data.entries.map((e:Row)=><tr key={e.id}><td>{time(e.created_at)}</td><td>{e.order_id.slice(0,8)}</td><td>{e.kind==="PAYMENT"?"Thu tiền":"Hoàn tiền"}</td><td>{e.method}</td><td>{cash(e.amount)}</td><td>{e.provider_ref}</td></tr>)}</tbody></table></div>
    </>}
  </>;
}

function ReviewManagement(props:BusinessProps) {
  const {data,error}=useLoad("/shop/reviews",props);const [busy,setBusy]=useState(false),[selected,setSelected]=useState<Row|null>(null);
  return <><BusinessHeading title="Đánh giá sản phẩm và người giao" sub="Lắng nghe phản hồi sau giao hàng và xử lý nội dung vi phạm." />{error&&<p role="alert">{error}</p>}{data?.map((r:Row)=><article className="panel review-card" key={r.id}><strong>{r.rating}/5 sao · {r.product_id?"Sản phẩm":"Người giao"}</strong><p>{r.comment||"Không có nhận xét"}</p><p className="muted">Đơn #{r.order_id.slice(0,8)} · {time(r.created_at)}</p>{r.hidden?<p>Đã ẩn: {r.hidden_reason}</p>:props.user.role==="ADMIN"&&<button disabled={!props.online||busy} onClick={()=>setSelected(r)}>Ẩn nội dung vi phạm</button>}</article>)}
    {selected&&<form className="panel" onSubmit={async e=>{e.preventDefault();const reason=new FormData(e.currentTarget).get("reason");setBusy(true);try{await props.mutate("/admin/reviews/"+selected.id+"/hide",{reason});setSelected(null);}finally{setBusy(false);}}}><label>Lý do ẩn<input name="reason" required maxLength={500}/></label><button disabled={busy||!props.online}>Xác nhận ẩn</button><button type="button" onClick={()=>setSelected(null)}>Đóng</button></form>}
  </>;
}

export function ProductReviews({ productId, request }: { productId:string; request:(path:string)=>Promise<any> }) {
  const [data,setData]=useState<Row|null>(null),[error,setError]=useState("");
  return <details className="product-reviews" onToggle={async e=>{if(e.currentTarget.open)try{setData(await request("/reviews/product/"+productId));}catch(e){setError((e as Error).message);}}}><summary>Xem đánh giá sản phẩm</summary>{error&&<p>{error}</p>}{data&&<><p>{data.count?`${Number(data.rating).toFixed(1)}/5 · ${data.count} đánh giá`:"Chưa có đánh giá"}</p>{data.reviews.map((r:Row)=><p key={r.id}>{r.rating}/5 · {r.comment}</p>)}</>}</details>;
}
