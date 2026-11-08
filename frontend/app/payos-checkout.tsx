"use client";

import { useEffect, useRef, useState } from "react";

type Row = Record<string, any>;
type Props = {
  payment: Row;
  request: (path: string) => Promise<any>;
  refresh: number;
  close: () => void;
};
const cash = (value: unknown) => new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(Number(value));

export default function PayosCheckout({ payment, request, refresh, close }: Props) {
  const root = useRef<HTMLElement>(null);
  const [order, setOrder] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    let live = true, checking = false;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        const next = await request("/orders/" + payment.order_id);
        if (live) { setOrder(next); setError(""); }
      } catch (e) { if (live) setError((e as Error).message); }
      finally { checking = false; }
    };
    void check();
    const timer = window.setInterval(check, 5000);
    return () => { live = false; window.clearInterval(timer); };
  }, [payment.order_id, request, refresh, reload]);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    root.current?.focus();
    return () => { document.body.style.overflow = overflow; previous?.isConnected && previous.focus(); };
  }, []);
  const paid = order?.payment_status === "PAID";
  const seconds = Math.max(0, Math.ceil((new Date(payment.expires_at).getTime() - clock) / 1000));
  const unavailable = seconds <= 0 || (order && order.status !== "APPROVED");
  const qr = typeof payment.qr_image === "string" && payment.qr_image.startsWith("data:image/png;base64,") ? payment.qr_image : null;
  return <div className="business-scrim" onClick={e => { if (e.target === e.currentTarget) close(); }}>
    <section className="business-dialog payos-dialog" role="dialog" aria-modal="true" aria-labelledby="payos-title" ref={root} tabIndex={-1} onKeyDown={e => {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Tab") {
        const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]') ?? []);
        const first = controls[0], last = controls.at(-1);
        if (e.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && (document.activeElement === last || document.activeElement === root.current)) { e.preventDefault(); first?.focus(); }
      }
    }}>
      <header className="row-heading"><div><div className="eyebrow">Thanh toán qua sàn</div><h2 id="payos-title">payOS · Quét QR thanh toán</h2></div><button className="ghost" aria-label="Đóng thanh toán" onClick={close}>✕</button></header>
      <p className="muted">Đơn #{String(payment.order_id).slice(0,8).toUpperCase()} · Tiền chuyển về tài khoản nhận của sàn.</p>
      {paid ? <div className="notice" role="status"><strong>Đã thanh toán thành công</strong><p>Server đã xác nhận nhận tiền. Shop sẽ tiếp tục chuẩn bị đơn hàng.</p></div> : unavailable ? <div className="notice warn" role="status">Mã thanh toán không còn hiệu lực. Đóng cửa sổ và kiểm tra trạng thái đơn trước khi thao tác tiếp.</div> : <>
        <strong className="payos-amount">{cash(payment.amount)}</strong>
        {qr ? <img className="payos-qr" src={qr} alt="Mã VietQR thanh toán đúng số tiền và nội dung của đơn" /> : <p className="notice">Mở trang payOS bên dưới để xem QR của đơn này.</p>}
        <dl className="payos-bank">
          {payment.account_name && <div><dt>Người nhận</dt><dd>{payment.account_name}</dd></div>}
          {payment.account_number && <div><dt>Tài khoản nhận</dt><dd>{payment.account_number}</dd></div>}
          <div><dt>Mã thanh toán</dt><dd>{payment.order_code}</dd></div>
          <div><dt>Còn hiệu lực</dt><dd>{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2,"0")}</dd></div>
        </dl>
        <p className="muted">Quét bằng ứng dụng ngân hàng, giữ nguyên số tiền và nội dung. Trạng thái sẽ tự cập nhật sau khi server xác minh giao dịch.</p>
        <a className="payos-hosted-link" href={payment.checkout_url} target="_blank" rel="noopener noreferrer">Mở trang thanh toán payOS ↗</a>
      </>}
      {error && <p className="notice warn" role="alert">Chưa kiểm tra được thanh toán: {error}. Không chuyển lại tiền khi chưa đối soát.</p>}
      <div className="actions"><button type="button" onClick={() => setReload(n => n + 1)}>Kiểm tra trạng thái</button><button type="button" className="primary" onClick={close}>{paid ? "Xong" : "Đóng"}</button></div>
    </section>
  </div>;
}
