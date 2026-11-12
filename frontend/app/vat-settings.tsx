"use client";

import { useState } from "react";
import { useLoad, type BusinessProps } from "./business-ui";

type Row = Record<string, any>;

export default function VatSettings(props: BusinessProps) {
  const policy = useLoad("/admin/vat",props);
  const [kind,setKind] = useState("categories");
  const [id,setId] = useState("");
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  const records = useLoad(kind==="products"?"/admin/products":"/admin/config/categories",props);
  const target = records.data?.find((row: Row) => row.id===id);
  const save = async (path: string, body: Row) => {
    setBusy(true); setMessage("");
    try {
      await props.mutate(path,body,"PATCH");
      setMessage("Đã lưu thuế suất.");
    } catch (failure) {
      setMessage((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return <details className="panel food-stock-section">
    <summary>Thuế VAT</summary>
    <p className="muted">Ưu tiên thuế suất sản phẩm, sau đó đến danh mục và mức mặc định. VAT tính trên tiền hàng thực bán.</p>
    {policy.data && <form className="food-fields" key={policy.data.version} onSubmit={e => {
      e.preventDefault();
      void save("/admin/vat",{rate:new FormData(e.currentTarget).get("rate"),expectedVersion:policy.data.version});
    }}>
      <label>Thuế suất mặc định (%)<input type="number" name="rate" min="0" max="100" step=".01" required defaultValue={policy.data.value.rate} /></label>
      <button disabled={busy || !props.online}>Lưu mức mặc định</button>
    </form>}
    <div className="food-fields">
      <label>Áp dụng riêng cho<select value={kind} onChange={e => {setKind(e.target.value);setId("");}}>
        <option value="categories">Danh mục</option><option value="products">Sản phẩm</option>
      </select></label>
      <label>{kind==="categories"?"Danh mục":"Sản phẩm"}<select value={id} onChange={e => setId(e.target.value)}>
        <option value="">Chọn đối tượng</option>
        {records.data?.map((row: Row) => <option key={row.id} value={row.id}>{row.name}</option>)}
      </select></label>
    </div>
    {target && <form className="food-fields" key={target.id+":"+target.version} onSubmit={e => {
      e.preventDefault();
      const rate = new FormData(e.currentTarget).get("rate");
      void save("/admin/vat/"+kind+"/"+target.id,{rate:rate===""?null:rate,expectedVersion:target.version});
    }}>
      <label>Thuế suất (%)<input type="number" name="rate" min="0" max="100" step=".01" placeholder="Để trống để kế thừa" defaultValue={target.vat_rate ?? ""} /></label>
      <button disabled={busy || !props.online}>Lưu mức áp dụng riêng</button>
    </form>}
    {(message || policy.error || records.error) && <p role="status">{message || policy.error || records.error}</p>}
  </details>;
}
