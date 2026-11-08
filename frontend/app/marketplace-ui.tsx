"use client";

import { useState, type FormEvent } from "react";
import { BusinessHeading, useLoad, type BusinessProps } from "./business-ui";

type Shop = { id: string; name: string; address: string };
type Bank = { bankName: string; accountHolder: string; accountNumber: string };
type Balance = { available: string; held: string; pending: string; paid: string; fees: string; month: string; used: number; limit: number; minimumBalance: string };
type Withdrawal = { id: string; amount: string; status: string; bank_snapshot: Bank; bank_reference?: string; decision_note?: string; created_at: string; version: string; shop_name?: string };
type Application = { id: string; status: string; version: string; profile_json: { name: string; address: string; description: string; phone: string }; decision_note?: string };
type Props = BusinessProps & { money: (amount: unknown) => string };
const labels: Record<string, string> = { PENDING: "Chờ duyệt", APPROVED: "Đã duyệt", REJECTED: "Từ chối", PAID: "Đã chi trả" };
const formatDate = (value: string) => new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" });

export function ShopSelect({ shops, value, onChange, allLabel, label = "Shop" }: {
  shops: Shop[]; value: string; onChange: (id: string) => void; allLabel?: string; label?: string;
}) {
  return (
    <label>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {allLabel && <option value="">{allLabel}</option>}
        {shops.map((shop) => <option value={shop.id} key={shop.id}>{shop.name}</option>)}
      </select>
    </label>
  );
}

function useAction(props: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (path: string, body: Record<string, unknown>, method = "POST") => {
    setBusy(true);
    setError("");
    try {
      await props.mutate(path, body, method);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy: busy || !props.online, error };
}

function Apply(props: Props) {
  const { data, error } = useLoad("/marketplace/application", props);
  const action = useAction(props);
  const application: Application | null = data?.application ?? null;
  return <>
    <BusinessHeading title="Đăng ký mở shop" sub="Gửi hồ sơ để quản trị xét duyệt. Sau khi được duyệt, tài khoản này chuyển sang vai trò người bán." />
    {(error || action.error) && <p className="notice error" role="alert">{error || action.error}</p>}
    {application && <p className="notice" role="status"><strong>{labels[application.status]}</strong> · {application.profile_json.name}{application.decision_note && ` · ${application.decision_note}`}</p>}
    {data && (!application || application.status === "REJECTED") && (
      <form className="panel form-grid" onSubmit={(e) => {
        e.preventDefault();
        void action.run("/marketplace/application", Object.fromEntries(new FormData(e.currentTarget)));
      }}>
        <label>Tên shop<input name="name" required maxLength={200} defaultValue={application?.profile_json.name} /></label>
        <label>Địa chỉ lấy hàng<input name="address" required maxLength={200} defaultValue={application?.profile_json.address} /></label>
        <label>Giới thiệu shop<textarea name="description" maxLength={2000} defaultValue={application?.profile_json.description} /></label>
        <div><button className="primary" disabled={action.busy}>Gửi hồ sơ</button></div>
      </form>
    )}
  </>;
}

function ShopApplications(props: Props) {
  const { data, error } = useLoad("/admin/shop-applications", props);
  const shops = useLoad("/marketplace/shops", props).data as Shop[] | null;
  const action = useAction(props);
  return <>
    <BusinessHeading title="Quản lý shop" sub="Xem shop đang hoạt động và xử lý hồ sơ đăng ký." />
    {(error || action.error) && <p className="notice error" role="alert">{error || action.error}</p>}
    <section className="market-finance-grid" aria-label="Shop đang hoạt động">
      {shops?.map((shop) => <article className="panel market-record" key={shop.id}><h2>{shop.name}</h2><p className="muted">{shop.address}</p></article>)}
    </section>
    <h2>Hồ sơ mở shop</h2>
    {data?.length === 0 && <p className="empty">Chưa có hồ sơ đăng ký.</p>}
    {(data as Application[] | null)?.map((application) => (
      <article className="panel market-record" key={application.id}>
        <div className="row-heading"><h3>{application.profile_json.name}</h3><span className={"status " + application.status}>{labels[application.status]}</span></div>
        <p>{application.profile_json.address} · {application.profile_json.phone}</p>
        <p className="muted">{application.profile_json.description}</p>
        {application.decision_note && <p>{application.decision_note}</p>}
        {application.status === "PENDING" && (
          <form className="form" onSubmit={(e: FormEvent<HTMLFormElement>) => {
            e.preventDefault();
            const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement;
            const approved = submitter?.value === "approve";
            const note = String(new FormData(e.currentTarget).get("note") ?? "");
            void action.run("/admin/shop-applications/" + application.id, { expectedVersion: application.version, approved, note }, "PATCH");
          }}>
            <label>Ghi chú xét duyệt<input name="note" maxLength={500} placeholder="Nhập lý do nếu từ chối" /></label>
            <div className="actions"><button className="primary" value="approve" disabled={action.busy}>Duyệt mở shop</button><button value="reject" disabled={action.busy}>Từ chối hồ sơ</button></div>
          </form>
        )}
      </article>
    ))}
  </>;
}

function BalanceCards({ balance, money }: { balance: Balance; money: Props["money"] }) {
  return <div className="business-metrics" aria-label="Số dư shop">
    <div>Số dư khả dụng · sau phí nền tảng<strong>{money(balance.available)}</strong></div>
    <div>Chờ hoàn tất đơn · sau phí<strong>{money(balance.held)}</strong></div>
    <div>Đang chờ chi<strong>{money(balance.pending)}</strong></div>
    <div>Đã nhận<strong>{money(balance.paid)}</strong></div>
    <div>Phí sàn đã ghi nhận<strong>{money(balance.fees)}</strong></div>
  </div>;
}

function SellerBalance(props: Props) {
  const { data, error } = useLoad("/shop/balance", props);
  const action = useAction(props);
  const [amount, setAmount] = useState("");
  const balance: Balance | undefined = data?.balance;
  const bank: Bank | undefined = data?.bank;
  const eligible = balance && BigInt(balance.available) >= BigInt(balance.minimumBalance) && balance.used < balance.limit;
  return <>
    <BusinessHeading title="Số dư và rút tiền" sub="Theo dõi tiền từ đơn đã giao và đã thực nhận, sau khi trừ phí sàn." />
    {(error || action.error) && <p className="notice error" role="alert">{error || action.error}</p>}
    {balance && <>
      <BalanceCards balance={balance} money={props.money} />
      <p className="muted">Tiền hàng sau phí nền tảng chờ giao thành công trước khi được rút. Phí giao và VAT không thuộc số dư shop; số dư khả dụng đã trừ tiền đang chờ rút và đã chi trả.</p>
      <p className="notice">Tháng {balance.month.slice(0, 7)} đã dùng <strong>{balance.used}/{balance.limit} lượt</strong>. Số dư khả dụng cần đạt {props.money(balance.minimumBalance)} để rút.</p>
      <div className="market-finance-grid">
        <form className="panel market-record form" key={bank ? bank.bankName + bank.accountNumber + bank.accountHolder : "new"} onSubmit={(e) => {
          e.preventDefault();
          void action.run("/shop/bank", Object.fromEntries(new FormData(e.currentTarget)), "PATCH");
        }}>
          <h2>Tài khoản nhận tiền</h2>
          <label>Ngân hàng<input name="bankName" defaultValue={bank?.bankName} required maxLength={100} /></label>
          <label>Chủ tài khoản<input name="accountHolder" defaultValue={bank?.accountHolder} required maxLength={100} /></label>
          <label>Số tài khoản<input name="accountNumber" inputMode="numeric" pattern="[0-9]{6,30}" defaultValue={bank?.accountNumber} required /></label>
          <button disabled={action.busy}>Lưu tài khoản ngân hàng</button>
        </form>
        <form className="panel market-record form" onSubmit={async (e) => {
          e.preventDefault();
          if (await action.run("/shop/withdrawals", { amount })) setAmount("");
        }}>
          <h2>Yêu cầu rút tiền</h2>
          <p className="muted">Quản trị chuyển khoản theo thông tin đã lưu trong yêu cầu. Khoản chờ chi được trừ khỏi số dư khả dụng.</p>
          <label>Số tiền muốn rút<input type="number" min="1" max={balance.available} step="1" required value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          <button className="primary" disabled={action.busy || !eligible || !bank}>Gửi yêu cầu rút</button>
        </form>
      </div>
      <h2>Lịch sử rút tiền</h2>
      {(data.withdrawals as Withdrawal[]).length === 0 && <p className="empty">Chưa có yêu cầu rút tiền.</p>}
      {(data.withdrawals as Withdrawal[]).map((row) => <article className="panel market-record" key={row.id}>
        <div className="row-heading"><strong>{props.money(row.amount)}</strong><span className={"status " + row.status}>{labels[row.status]}</span></div>
        <p className="muted">{formatDate(row.created_at)} · {row.bank_snapshot.bankName} · …{row.bank_snapshot.accountNumber.slice(-4)}</p>
        {row.bank_reference && <p>Mã chuyển khoản {row.bank_reference}</p>}
        {row.decision_note && <p>{row.decision_note}</p>}
      </article>)}
    </>}
  </>;
}

function AdminWithdrawals(props: Props) {
  const [shopId, setShopId] = useState("");
  const shops = useLoad("/marketplace/shops", props).data as Shop[] | null;
  const { data, error } = useLoad("/admin/withdrawals" + (shopId ? "?shopId=" + shopId : ""), props);
  const overview = useLoad(shopId ? "/admin/shop-balance?shopId=" + shopId : null, props).data;
  const fee = useLoad("/admin/platform-fee", props).data;
  const action = useAction(props);
  return <>
    <BusinessHeading title="Đối soát và chi trả shop" sub="Cấu hình phí sàn và xác nhận các khoản chuyển ngân hàng cho từng shop." />
    {(error || action.error) && <p className="notice error" role="alert">{error || action.error}</p>}
    {fee && <form key={fee.version} className="panel market-record business-assign" onSubmit={(e) => {
      e.preventDefault();
      void action.run("/admin/platform-fee", { rate: new FormData(e.currentTarget).get("rate"), expectedVersion: fee.version }, "PATCH");
    }}>
      <label>Phí sàn trên tiền hàng (%)<input name="rate" type="number" min="0" max="100" step="0.01" required defaultValue={fee.rate} /></label>
      <button disabled={action.busy}>Lưu phí cho đơn mới</button>
    </form>}
    <div className="toolbar"><ShopSelect shops={shops ?? []} value={shopId} onChange={setShopId} allLabel="Tất cả shop" /></div>
    {overview?.shopId === shopId && overview && <BalanceCards balance={overview.balance} money={props.money} />}
    <h2>Yêu cầu rút tiền</h2>
    {data?.length === 0 && <p className="empty">Chưa có yêu cầu rút tiền.</p>}
    {(data as Withdrawal[] | null)?.map((row) => (
      <article className="panel market-record" key={row.id}>
        <div className="row-heading"><h3>{row.shop_name} · {props.money(row.amount)}</h3><span className={"status " + row.status}>{labels[row.status]}</span></div>
        <p>{row.bank_snapshot.bankName} · {row.bank_snapshot.accountNumber} · {row.bank_snapshot.accountHolder}</p>
        <p className="muted">Yêu cầu lúc {formatDate(row.created_at)}{row.bank_reference && ` · Mã chuyển khoản ${row.bank_reference}`}</p>
        {row.decision_note && <p>{row.decision_note}</p>}
        {row.status === "PENDING" && <form className="form" onSubmit={(e) => {
          e.preventDefault();
          const status = ((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)?.value;
          const form = new FormData(e.currentTarget);
          if (status === "PAID" && !window.confirm(`Xác nhận đã chuyển ${props.money(row.amount)} cho ${row.shop_name}?`)) return;
          void action.run("/admin/withdrawals/" + row.id, { status, reference: form.get("reference"), note: form.get("note"), expectedVersion: row.version }, "PATCH");
        }}>
          <label>Mã chuyển khoản<input name="reference" maxLength={128} /></label>
          <label>Ghi chú<input name="note" maxLength={500} placeholder="Nhập lý do nếu từ chối" /></label>
          <div className="actions"><button value="PAID" className="primary" disabled={action.busy}>Xác nhận đã chi</button><button value="REJECTED" disabled={action.busy}>Từ chối yêu cầu</button></div>
        </form>}
      </article>
    ))}
  </>;
}

export default function MarketplaceScreen(props: Props) {
  if (props.kind === "apply") return <Apply {...props} />;
  if (props.kind === "shops") return <ShopApplications {...props} />;
  if (props.kind === "balance") return <SellerBalance {...props} />;
  return <AdminWithdrawals {...props} />;
}
