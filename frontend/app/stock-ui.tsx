"use client";

import { Fragment, useId, useState, type FormEvent } from "react";
import { BusinessHeading, useLoad, type BusinessProps } from "./business-ui";

type Row = Record<string, any>;
type Line = { key: string; productId: string; quantity: string; unitCost: string };
type LineErrors = { quantity?: string; unitCost?: string };
const moneyFormat = new Intl.NumberFormat("vi-VN", { style:"currency",currency:"VND" });
const cash = (value: unknown) => {
  const amount = String(value ?? 0);
  return moneyFormat.format(/^-?\d+(?:\.0+)?$/.test(amount) ? BigInt(amount.split(".")[0]) : Number(amount));
};
const formatQty = (value: unknown) => Number(value ?? 0).toLocaleString("vi-VN", {maximumFractionDigits:3});
const time = (value: string) => new Date(value).toLocaleString("vi-VN", {timeZone:"Asia/Ho_Chi_Minh"});
const movementLabels: Record<string,string> = {
  OPENING:"Kiểm kê đầu kỳ", PURCHASE:"Nhập hàng", APPROVE:"Duyệt đơn", CANCEL_RESTORE:"Hoàn do hủy",
  DELIVERY_RETURN:"Hàng giao hoàn", PAYMENT_EXPIRED:"Hoàn do hết hạn thanh toán", ADJUSTMENT:"Điều chỉnh",
};

function receiptLineTotal(line: Line) {
  if (!line.productId || !/^\d+(?:\.\d{1,3})?$/.test(line.quantity) || !/^\d+$/.test(line.unitCost)) return null;
  const [whole, fraction = ""] = line.quantity.split(".");
  const thousandths = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, "0"));
  return (thousandths * BigInt(line.unitCost) + 500n) / 1000n;
}

function lineErrors(line: Line, product: Row | undefined, kind: string): LineErrors {
  const errors: LineErrors = {};
  const quantity = line.quantity;
  if (!/^\d+(?:\.\d{1,3})?$/.test(quantity)) errors.quantity = "Nhập số lượng hợp lệ, tối đa 3 chữ số thập phân.";
  else {
    const [whole, fraction = ""] = quantity.split(".");
    const thousandths = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, "0"));
    const [stepWhole, stepFraction = ""] = String(product?.quantity_step ?? "0.001").split(".");
    const step = BigInt(stepWhole) * 1000n + BigInt(stepFraction.padEnd(3, "0").slice(0, 3));
    if (thousandths > 999999999999n || (kind === "PURCHASE" && thousandths === 0n)) errors.quantity = "Số lượng phải lớn hơn 0 và trong giới hạn kho.";
    else if (!step || thousandths % step !== 0n) errors.quantity = `Số lượng phải theo bước ${product?.quantity_step ?? "0.001"} ${product?.unit ?? ""}.`;
  }
  if (!/^\d+$/.test(line.unitCost) || BigInt(line.unitCost || "0") > 999999999999999999n)
    errors.unitCost = "Nhập giá nguyên không âm, tối đa 18 chữ số.";
  return errors;
}

function ReceiptAmounts({ row }: { row: Row }) {
  if (row.kind === "OPENING") {
    return <div className="food-receipt-amounts"><strong>{cash(row.total)}</strong><small>Giá trị tồn đầu kỳ</small></div>;
  }
  const owes = Number(row.outstanding) > 0;
  return (
    <div className="food-receipt-amounts">
      <span>Tổng tiền nhập <strong>{cash(row.total)}</strong></span>
      {owes
        ? <strong className="status DEBT">Còn nợ {cash(row.outstanding)}{row.overdue ? " · Quá hạn" : ""}</strong>
        : <strong className="status PAID">Đã trả đủ · {cash(row.paid)}</strong>}
    </div>
  );
}

function SupplierPaymentForm({ receipt, disabled, onPayment }: {
  receipt: Row;
  disabled: boolean;
  onPayment: (amount: string, reference: string) => Promise<boolean>;
}) {
  const [amount, setAmount] = useState("");
  const errorId = useId();
  const outstanding = BigInt(String(receipt.outstanding).split(".")[0]);
  const entered = /^\d+$/.test(amount) ? BigInt(amount) : 0n;
  const tooHigh = entered > outstanding;
  const invalid = amount !== "" && (entered === 0n || tooHigh);
  return <form className="food-receipt-payment" aria-label="Trả công nợ" onSubmit={async event => {
    event.preventDefault();
    if (disabled || entered === 0n || tooHigh) return;
    const form = event.currentTarget;
    const reference = String(new FormData(form).get("reference") ?? "").trim();
    if (reference && await onPayment(String(entered), reference)) {
      form.reset();
      setAmount("");
    }
  }}>
    <p>Còn nợ <strong className="is-owed">{cash(outstanding)}</strong></p>
    <div className="food-receipt-payment-controls">
      <label>Số tiền trả (đ)
        <input type="number" inputMode="numeric" min="1" step="1" max={String(outstanding)} required
          value={amount} disabled={disabled} onChange={event => setAmount(event.target.value)}
          aria-invalid={invalid} aria-describedby={invalid ? errorId : undefined} />
      </label>
      <button type="button" disabled={disabled} onClick={() => setAmount(String(outstanding))}>Trả đủ</button>
    </div>
    {invalid && <p id={errorId} className="is-owed" role="alert">
      {tooHigh ? "Số tiền trả vượt khoản còn nợ." : "Nhập số tiền nguyên lớn hơn 0."}
    </p>}
    {entered > 0n && !tooHigh && <p>
      Còn nợ sau khi trả <strong className={entered === outstanding ? "is-paid" : "is-owed"}>{cash(outstanding - entered)}</strong>
    </p>}
    <label>Mã giao dịch / chứng từ<input name="reference" required maxLength={150} disabled={disabled} /></label>
    <div className="actions"><button className="primary" disabled={disabled || entered === 0n || tooHigh}>
      Xác nhận đã trả
    </button></div>
  </form>;
}

export default function StockScreen(props: BusinessProps) {
  const [tab,setTab] = useState("balance");
  const [search,setSearch] = useState("");
  const [category,setCategory] = useState("all");
  const [receiptCategory,setReceiptCategory] = useState("all");
  const [receiptSearch,setReceiptSearch] = useState("");
  const [showLineErrors,setShowLineErrors] = useState(false);
  const [page,setPage] = useState(0);
  const [selected,setSelected] = useState("");
  const [paymentOpen,setPaymentOpen] = useState(false);
  const [productId,setProductId] = useState("");
  const [receiptKind,setReceiptKind] = useState("PURCHASE");
  const [lines,setLines] = useState<Line[]>([]);
  const [paidDraft,setPaidDraft] = useState("");
  const [payInFull,setPayInFull] = useState(false);
  const [supplier,setSupplier] = useState<Row | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const levels = useLoad("/admin/stock",props);
  const suppliers = useLoad(["receipt","suppliers"].includes(tab) ? "/admin/stock/suppliers" : null,props);
  const showReceipts = tab==="receipt" || tab==="debt";
  const receipts = useLoad(showReceipts ? "/admin/stock/receipts?page="+page+(tab==="debt"?"&kind=PURCHASE":"") : null,props);
  const ledger = useLoad(tab==="ledger" ? "/admin/stock/ledger?page="+page+(productId?"&productId="+productId:"") : null,props);
  const detail = useLoad(showReceipts && selected ? "/admin/stock/receipts/"+selected : null,props);
  const summary = useLoad(props.user.role==="ADMIN" && tab==="debt" ? "/admin/supplier-summary" : null,props);
  const disabled = busy || !props.online;
  const products: Row[] = levels.data ?? [];
  const categories = Array.from(new Map(products.filter(row => row.category_id && row.category_name)
    .map(row => [row.category_id, row.category_name])).entries()).sort((a, b) => String(a[1]).localeCompare(String(b[1]), "vi"));
  const activeSuppliers: Row[] = (suppliers.data ?? []).filter((row: Row) => row.active);
  const validation = lines.map(line => lineErrors(line, products.find(row => row.id === line.productId), receiptKind));
  const lineTotals = lines.map((line, index) => Object.keys(validation[index]).length ? null : receiptLineTotal(line));
  const receiptTotal = lineTotals.length && lineTotals.every(total => total !== null)
    ? lineTotals.reduce<bigint>((sum, total) => sum + (total ?? 0n), 0n)
    : null;
  const paidAmount = payInFull && receiptTotal !== null ? String(receiptTotal) : paidDraft;
  const paidIsWhole = /^\d+$/.test(paidAmount);
  const invalidPaid = receiptKind==="PURCHASE" && paidAmount !== "" && !paidIsWhole;
  const parsedPaid = paidIsWhole ? BigInt(paidAmount) : 0n;
  const paidTooHigh = receiptKind==="PURCHASE" && receiptTotal !== null && parsedPaid > receiptTotal;
  const run = async (path: string,body: Row,method = "POST") => {
    if (disabled) return null;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await props.mutate(path,body,method);
      setNotice("Đã ghi nhận.");
      return result;
    } catch (failure) {
      setError((failure as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  };
  const openTab = (value: string) => {
    setTab(value); setPage(0); setSelected(""); setError(""); setNotice("");
  };
  const changeLine = (key: string, change: Partial<Line>) =>
    setLines(rows => rows.map(row => row.key===key ? {...row,...change} : row));
  const receive = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    setShowLineErrors(true);
    if (!lines.length || validation.some(row => Object.keys(row).length)) {
      setError(!lines.length ? "Hãy chọn ít nhất một sản phẩm." : "Kiểm tra các dòng sản phẩm được đánh dấu trước khi nhập kho.");
      return;
    }
    if (receiptKind === "PURCHASE" && !new FormData(form).get("supplierId")) {
      setError("Hãy chọn nhà cung cấp cho phiếu nhập."); return;
    }
    if (invalidPaid || paidTooHigh || (payInFull && receiptTotal === null)) return;
    if (!window.confirm("Xác nhận nhập số lượng và giá vốn đã khai báo vào kho?")) return;
    const result = await run("/admin/stock/receipts",{...Object.fromEntries(new FormData(form)),kind:receiptKind,
      paidAmount:receiptKind==="PURCHASE" ? paidAmount || "0" : "0",
      items:lines.map(({productId,quantity,unitCost}) => ({productId,quantity,unitCost}))});
    if (result) {
      form.reset();
      setLines([]);
      setShowLineErrors(false);
      setPaidDraft("");
      setPayInFull(false);
      setPage(0);
      setSelected(result.id);
      setNotice("Đã nhập kho và cập nhật số lượng tồn.");
    }
  };
  const visible = products.filter(row => (category === "all" || row.category_id === category) && [row.name,row.sku].some(value =>
    String(value).toLocaleLowerCase("vi").includes(search.trim().toLocaleLowerCase("vi"))));
  const receiptProducts = products.filter(row => (receiptKind !== "OPENING" || !row.opened) &&
    (receiptCategory === "all" || row.category_id === receiptCategory) &&
    [row.name, row.sku].some(value => String(value).toLocaleLowerCase("vi").includes(receiptSearch.trim().toLocaleLowerCase("vi"))));
  const receipt = detail.data?.id === selected ? detail.data : null;
  const currentPage = showReceipts ? receipts.data : ledger.data;
  const failures = [levels.error,suppliers.error,receipts.error,ledger.error,detail.error,summary.error];
  const payReceipt = async (id: string, amount: string, reference: string) => {
    const payment = await run("/admin/supplier-payments/"+id, {amount, reference});
    if (!payment) return false;
    const withBalance = (row: Row) => BigInt(String(row.paid).split(".")[0]) > BigInt(String(payment.paid).split(".")[0]) ? row : ({
      ...row, paid: payment.paid, outstanding: payment.outstanding,
      overdue: Number(payment.outstanding) > 0 && row.overdue,
    });
    receipts.setData((rows: Row[] | null) => rows?.map(row => row.id === id ? withBalance(row) : row) ?? null);
    detail.setData((row: Row | null) => row?.id === id ? {
      ...withBalance(row), payments: row.payments.some((previous: Row) => previous.id === payment.id)
        ? row.payments : [...row.payments, payment],
    } : row);
    setNotice(Number(payment.outstanding) > 0
      ? `Đã ghi nhận ${cash(amount)}. Còn nợ ${cash(payment.outstanding)}.`
      : "Đã ghi nhận thanh toán. Phiếu đã trả đủ.");
    if (Number(payment.outstanding) === 0) setPaymentOpen(false);
    return true;
  };
  return <>
    <BusinessHeading title="Kho và nhà cung cấp" sub="Kiểm kê, nhập hàng, theo dõi biến động và công nợ theo phiếu." />
    <nav className="food-stock-tabs" aria-label="Nghiệp vụ kho">
      {[["balance","Tồn kho"],["receipt","Nhập kho"],["debt","Công nợ"],
        ["ledger","Sổ kho"],["suppliers","Nhà cung cấp"],["adjust","Điều chỉnh"]].map(([id,label]) =>
        <button key={id} type="button" className={tab===id?"primary":""} aria-pressed={tab===id}
          onClick={() => openTab(id)}>{label}</button>)}
    </nav>
    {(error || failures.find(Boolean)) && <p className="notice error" role="alert">{error || failures.find(Boolean)}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {tab==="balance" && <section className="panel food-stock-section">
      <div className="food-fields stock-filters">
        <label>Danh mục<select value={category} onChange={event => setCategory(event.target.value)}><option value="all">Tất cả danh mục</option>{categories.map(([id,name]) => <option key={String(id)} value={String(id)}>{String(name)}</option>)}</select></label>
        <label>Tìm sản phẩm hoặc SKU<input type="search" placeholder="Nhập tên hoặc mã SKU" value={search} onChange={event => setSearch(event.target.value)} /></label>
      </div>
      <p className="muted stock-result-count">Hiển thị {visible.length} / {products.length} sản phẩm</p>
      <div className="food-stock-list">{visible.map(row => <article className="food-stock-row" key={row.id}>
        <div><strong>{row.name}</strong><small>{row.sku} · {row.category_name || "Chưa phân loại"} · {row.unit}</small></div>
        <div><strong>{formatQty(row.quantity)} {row.unit}</strong><small>{row.average_cost==null?"Chưa có giá vốn":cash(row.average_cost)+" / "+row.unit}</small></div>
        <button type="button" onClick={() => {setProductId(row.id); openTab("ledger");}}>Biến động</button>
      </article>)}</div>
      {levels.data && visible.length===0 && <p>Không tìm thấy sản phẩm.</p>}
    </section>}
    {tab==="receipt" && <form className="panel food-stock-section" onSubmit={receive} noValidate>
      <div className="food-fields">
        <label>Loại phiếu<select value={receiptKind} onChange={event => {
          setReceiptKind(event.target.value);
          setLines([]);
          setShowLineErrors(false);
          setPaidDraft("");
          setPayInFull(false);
        }}>
          <option value="PURCHASE">Nhập hàng từ nhà cung cấp</option><option value="OPENING">Kiểm kê đầu kỳ</option>
        </select></label>
        {receiptKind==="PURCHASE" && <>
          <label>Nhà cung cấp<select name="supplierId" required><option value="">Chọn nhà cung cấp</option>
            {activeSuppliers.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select></label>
          <label>Số hóa đơn / chứng từ<input name="invoiceNumber" maxLength={100} /></label>
          <label>Hạn thanh toán<input name="dueDate" type="date" /></label>
        </>}
      </div>
      <section className="receipt-picker" aria-label="Chọn sản phẩm nhập kho">
        <div className="receipt-picker-heading"><div><h2>Chọn sản phẩm nhập kho</h2><p className="muted">Tích chọn nhiều sản phẩm, sau đó nhập số lượng và giá cho từng món.</p></div><strong>{lines.length}/100 đã chọn</strong></div>
        <div className="food-fields"><label>Danh mục<select value={receiptCategory} onChange={event => setReceiptCategory(event.target.value)}><option value="all">Tất cả danh mục</option>{categories.map(([id,name]) => <option key={String(id)} value={String(id)}>{String(name)}</option>)}</select></label>
          <label>Tìm sản phẩm hoặc SKU<input type="search" value={receiptSearch} placeholder="Nhập tên hoặc mã SKU" onChange={event => setReceiptSearch(event.target.value)} /></label></div>
        <div className="receipt-picker-list">{receiptProducts.map(row => {
          const selectedLine = lines.find(line => line.productId === row.id);
          return <label key={row.id} className={'receipt-picker-item' + (selectedLine ? ' selected' : '')}>
            <input type="checkbox" checked={!!selectedLine} disabled={disabled || (!selectedLine && lines.length >= 100)} onChange={event => {
              if (event.target.checked) setLines(current => current.some(line => line.productId === row.id) ? current : [...current, {key: crypto.randomUUID(), productId: row.id, quantity: '', unitCost: ''}]);
              else setLines(current => current.filter(line => line.productId !== row.id));
            }} />
            <span className="receipt-picker-image">{row.image && <img src={row.image.source_url || (row.image.asset_id ? "/api/v1/media/" + encodeURIComponent(row.image.asset_id) : "")} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true; }} />}</span>
            <span><strong>{row.name}</strong><small>{row.sku} · {row.unit} · Tồn {formatQty(row.quantity)} {row.unit}</small></span>
          </label>;
        })}</div>
        {!receiptProducts.length && <p className="muted">Không có sản phẩm phù hợp.</p>}
      </section>
      <div className="receipt-selected-heading"><h2>Mặt hàng đã chọn</h2><span>{lines.length} sản phẩm</span></div>
      {!lines.length && <p className="muted">Chọn sản phẩm phía trên để nhập số lượng và giá.</p>}
      {lines.map((line,index) => {
        const product = products.find(row => row.id===line.productId);
        const problem = showLineErrors ? validation[index] : {};
        return <fieldset className="food-receipt-line" key={line.key}>
          <legend>Mặt hàng {index+1}</legend>
          <div className="receipt-line-name"><strong>{product?.name ?? "Sản phẩm không còn khả dụng"}</strong><small>{product?.sku} · {product?.unit}</small></div>
          <label>Số lượng {product?.unit}<input type="number" required value={line.quantity}
            min={receiptKind==="OPENING"?"0":product?.quantity_step ?? "0.001"} step={product?.quantity_step ?? "0.001"}
            aria-invalid={!!problem.quantity} aria-describedby={problem.quantity ? `quantity-error-${line.key}` : undefined}
            onChange={event => changeLine(line.key,{quantity:event.target.value})} />{problem.quantity && <small id={`quantity-error-${line.key}`} className="is-owed">{problem.quantity}</small>}</label>
          <label>Giá nhập / đơn vị (đ)<input type="number" required min="0" step="1" value={line.unitCost}
            aria-invalid={!!problem.unitCost} aria-describedby={problem.unitCost ? `cost-error-${line.key}` : undefined}
            onChange={event => changeLine(line.key,{unitCost:event.target.value})} />{problem.unitCost && <small id={`cost-error-${line.key}`} className="is-owed">{problem.unitCost}</small>}</label>
          <button type="button" onClick={() => setLines(rows => rows.filter(row => row.key!==line.key))}>Bỏ chọn</button>
        </fieldset>;
      })}
      <div className="food-receipt-payment">
        <p>Tổng tiền nhập <strong>{receiptTotal === null ? "—" : cash(receiptTotal)}</strong></p>
        {receiptKind==="PURCHASE" && <>
          <div className="food-receipt-payment-controls">
            <label>Tiền trả trước (đ)
              <input type="number" min="0" step="1" inputMode="numeric" placeholder="0" value={paidAmount}
                aria-invalid={invalidPaid || paidTooHigh}
                aria-describedby={invalidPaid || paidTooHigh ? "upfront-payment-error" : undefined}
                onChange={event => {setPayInFull(false); setPaidDraft(event.target.value);}} />
            </label>
            <button type="button" aria-pressed={payInFull} disabled={disabled || receiptTotal === null}
              onClick={() => setPayInFull(true)}>Trả đủ</button>
          </div>
          {(invalidPaid || paidTooHigh) && <p id="upfront-payment-error" className="is-owed" role="alert">
            {invalidPaid ? "Nhập số tiền nguyên không âm." : "Tiền trả trước không được lớn hơn tổng tiền nhập."}
          </p>}
          {receiptTotal !== null && !invalidPaid && !paidTooHigh && <p>
            Còn nợ sau khi nhập <strong className={receiptTotal > parsedPaid ? "is-owed" : "is-paid"}>{cash(receiptTotal - parsedPaid)}</strong>
          </p>}
        </>}
      </div>
      <label>Ghi chú<input name="note" maxLength={500} /></label>
      <div className="actions"><button className="primary" disabled={disabled || !lines.length || invalidPaid || paidTooHigh ||
          (payInFull && receiptTotal === null) || (receiptKind==="PURCHASE" && !activeSuppliers.length)}>Xác nhận nhập kho</button></div>
    </form>}
    {showReceipts && <section className="panel food-stock-section" aria-label={tab==="debt" ? "Công nợ nhà cung cấp" : "Lịch sử nhập kho"}>
      <h2>{tab==="debt" ? "Công nợ nhà cung cấp" : "Lịch sử nhập kho"}</h2>
      {summary.data && <div className="food-fields" aria-label="Tổng công nợ nhà cung cấp">
        <p>Tiền nhập <strong>{cash(summary.data.purchased)}</strong></p><p>Đã trả <strong>{cash(summary.data.paid)}</strong></p>
        <p>Còn nợ <strong>{cash(summary.data.outstanding)}</strong></p><p>Quá hạn <strong>{cash(summary.data.overdue)}</strong></p>
      </div>}
      {receipts.data?.length===0 && <p>Chưa có phiếu.</p>}
      <div className="food-stock-list">{receipts.data?.map((row: Row) => <Fragment key={row.id}>
        <article className="food-stock-row">
        <div><strong>{row.supplier_name ?? "Kiểm kê đầu kỳ"}</strong><small>{row.invoice_number || row.id.slice(0,8)} · {time(row.confirmed_at)}</small></div>
        <ReceiptAmounts row={row} />
        <div className="food-stock-row-actions">
          <button type="button" aria-expanded={selected===row.id && !paymentOpen} onClick={() => {
            setSelected(selected===row.id && !paymentOpen ? "" : row.id);
            setPaymentOpen(false);
          }}>Chi tiết</button>
          {tab==="debt" && props.user.role==="ADMIN" && Number(row.outstanding)>0 &&
            <button type="button" className="primary" disabled={disabled} aria-expanded={selected===row.id && paymentOpen}
              onClick={() => {
                setSelected(selected===row.id && paymentOpen ? "" : row.id);
                setPaymentOpen(!(selected===row.id && paymentOpen));
              }}>Trả nợ</button>}
        </div>
        </article>
      {selected===row.id && !receipt && !detail.error && <p role="status">Đang tải phiếu…</p>}
      {receipt?.id===row.id && <section className="food-stock-detail" aria-label="Chi tiết phiếu nhập">
        <div className="row-heading"><h2>Phiếu {receipt.invoice_number || receipt.id.slice(0,8)}</h2><button onClick={() => setSelected("")}>Đóng</button></div>
        {paymentOpen && tab==="debt" && props.user.role==="ADMIN" && Number(receipt.outstanding)>0 &&
          <SupplierPaymentForm key={receipt.id} receipt={receipt} disabled={disabled}
            onPayment={(amount, reference) => payReceipt(receipt.id, amount, reference)} />}
        {receipt.note && <p>{receipt.note}</p>}
        {receipt.due_date && <p>Hạn thanh toán {receipt.due_date}</p>}
        <ul>{receipt.items.map((row: Row) => <li key={row.product_id}>{row.name} · {formatQty(row.quantity)} × {cash(row.unit_cost)}</li>)}</ul>
        {receipt.supplier_id && <>
          <h3>Lịch sử thanh toán</h3>
          {receipt.payments.length===0 && <p className="muted">Chưa ghi nhận khoản đã trả.</p>}
          <ul>{receipt.payments.map((row: Row) => <li key={row.id}>{time(row.paid_at)} · {cash(row.amount)} · {row.reference}</li>)}</ul>
        </>}
      </section>}
      </Fragment>)}</div>
    </section>}
    {tab==="ledger" && <section className="panel food-stock-section">
      <label>Lọc theo sản phẩm<select value={productId} onChange={event => {setProductId(event.target.value);setPage(0);}}>
        <option value="">Tất cả sản phẩm</option>{products.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select></label>
      {ledger.data?.length===0 && <p>Chưa có biến động.</p>}
      <div className="food-stock-list">{ledger.data?.map((row: Row) => <article className="food-stock-row" key={row.id}>
        <div><strong>{row.name}</strong><small>{movementLabels[row.kind] ?? row.kind} · {time(row.created_at)}</small></div>
        <div><strong>{Number(row.delta)>0?"+":""}{formatQty(row.delta)}</strong><small>Sau giao dịch {formatQty(row.balance_after)}</small></div>
        {row.reason && <small>{row.reason}</small>}
      </article>)}</div>
    </section>}
    {(showReceipts || tab==="ledger") && <div className="actions">
      <button disabled={page===0} onClick={() => {setSelected(""); setPage(page-1);}}>Trang trước</button>
      <button disabled={!currentPage || currentPage.length<50} onClick={() => {setSelected(""); setPage(page+1);}}>Trang sau</button>
    </div>}
    {tab==="suppliers" && <section className="panel food-stock-section">
      <button className="primary" type="button" onClick={() => setSupplier({active:true})}>Thêm nhà cung cấp</button>
      {supplier && <form className="food-fields" key={supplier.id ?? "new"} onSubmit={async event => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        if (await run("/admin/stock/suppliers"+(supplier.id?"/"+supplier.id:""),{
          name:data.get("name"),contact:data.get("contact"),active:data.has("active"),expectedVersion:supplier.version,
        },supplier.id?"PATCH":"POST")) setSupplier(null);
      }}>
        <label>Tên<input name="name" required maxLength={150} defaultValue={supplier.name} /></label>
        <label>Liên hệ<input name="contact" maxLength={200} defaultValue={supplier.contact} /></label>
        <label className="check"><input name="active" type="checkbox" defaultChecked={supplier.active} /> Đang giao dịch</label>
        <div className="actions"><button className="primary" disabled={disabled}>Lưu</button><button type="button" onClick={() => setSupplier(null)}>Đóng</button></div>
      </form>}
      <div className="food-stock-list">{suppliers.data?.map((row: Row) => <article className="food-stock-row" key={row.id}>
        <div><strong>{row.name}</strong><small>{row.contact || "Chưa có liên hệ"}</small></div>
        <span className={"status " + (row.active ? "ACTIVE" : "INACTIVE")}>{row.active?"Đang giao dịch":"Đã ngừng"}</span><button type="button" onClick={() => setSupplier(row)}>Sửa</button>
      </article>)}</div>
    </section>}
    {tab==="adjust" && <form className="panel food-stock-section" onSubmit={async event => {
      event.preventDefault();
      const form = event.currentTarget;
      if (await run("/admin/stock/adjustments",Object.fromEntries(new FormData(form)))) form.reset();
    }}>
      <label>Sản phẩm<select name="productId" required><option value="">Chọn sản phẩm</option>
        {products.filter(row => row.opened).map(row => <option key={row.id} value={row.id}>{row.name} · Còn {formatQty(row.quantity)} {row.unit}</option>)}
      </select></label>
      <label>Lượng điều chỉnh<input name="delta" type="number" step="0.001" required placeholder="Ví dụ -2 khi hao hụt" /></label>
      <label>Lý do<input name="reason" maxLength={500} required /></label>
      <button className="primary" disabled={disabled}>Ghi biến động</button>
    </form>}
  </>;
}
