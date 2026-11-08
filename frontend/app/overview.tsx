"use client";

import { useState } from "react";
import { FontAwesomeIcon as Icon } from "@fortawesome/react-fontawesome";
import { faClipboardList, faTruck, faCoins, faChartLine } from "@fortawesome/free-solid-svg-icons";

export type OverviewData = {
  from: string;
  to: string;
  totals: {
    createdOrders: number;
    orders: number;
    merchandise: string;
    grossProfit: string | null;
    platformFees: string;
    afterPlatformFees: string;
    profitAfterFees: string | null;
    averageOrderValue: string | null;
    cost: string | null;
    shipping: string;
    vat: string;
    missingCostLines: number;
  };
  daily: { day: string; orders: number; merchandise: string }[];
  statuses: { status: string; count: number }[];
  topProducts: {
    productId: string;
    name: string;
    quantity: string;
    unit: string;
    merchandise: string;
    grossProfit: string | null;
  }[];
};

const number = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 3 });
const dateLabel = (day: string) => day.slice(8, 10) + "/" + day.slice(5, 7);
const fullDate = (day: string) => day.split("-").reverse().join("/");

type Props = {
  data: OverviewData;
  money: (value: unknown) => string;
  statusLabels: Record<string, string>;
  afterPlatformFee?: boolean;
};

export default function OverviewDashboard({ data, money, statusLabels, afterPlatformFee = false }: Props) {
  const totals = data.totals;
  const [metric, setMetric] = useState<"merchandise" | "orders">("merchandise");
  const [selectedDay, setSelectedDay] = useState("");
  const bucketSize = Math.ceil(data.daily.length / 14);
  const buckets = [];
  for (let index = 0; index < data.daily.length; index += bucketSize) {
    const days = data.daily.slice(index, index + bucketSize);
    buckets.push({
      start: days[0].day,
      end: days[days.length - 1].day,
      orders: days.reduce((sum, row) => sum + row.orders, 0),
      merchandise: days.reduce((sum, row) => sum + BigInt(row.merchandise), BigInt(0)),
    });
  }
  const selected = buckets.find((bucket) => bucket.start === selectedDay) ?? buckets[buckets.length - 1];
  const peak = Math.max(1, ...buckets.map((bucket) => Number(bucket[metric])));
  const formatMetric = (value: number | bigint) => metric === "orders"
    ? number.format(value) + " đơn"
    : money(value);
  const dayRange = (start: string, end: string) => start === end
    ? fullDate(start)
    : fullDate(start) + " – " + fullDate(end);
  const profit = afterPlatformFee ? totals.profitAfterFees : totals.grossProfit;
  const metrics = [
    { label: "Số đơn hàng", value: number.format(totals.createdOrders), note: "Đơn được tạo trong kỳ", icon: faClipboardList },
    { label: "Giao thành công", value: number.format(totals.orders), note: "Đơn hoàn tất giao nhận trong kỳ", icon: faTruck },
    { label: "Doanh thu trước phí", value: money(totals.merchandise), note: "Tiền hàng đã giao, tách phí giao và VAT", icon: faCoins },
    { label: afterPlatformFee ? "Lãi sau phí" : "Lãi gộp", value: profit === null ? "Chưa đủ dữ liệu" : money(profit), note: afterPlatformFee ? "Doanh thu trừ giá vốn và phí nền tảng" : "Doanh thu hàng trừ giá vốn", icon: faChartLine },
  ];
  return (
    <div className="overview-dashboard">
      <section className="overview-kpis" aria-label="Chỉ số kinh doanh">
        {metrics.map(({ label, value, note, icon }, index) => (
          <article className={`overview-kpi overview-kpi-${index + 1}`} key={label}>
            <div className="overview-kpi-heading"><h2>{label}</h2><Icon icon={icon} aria-hidden="true" /></div>
            <strong className={index === 3 && profit !== null && Number(profit) < 0 ? "overview-loss" : ""}>{value}</strong>
            <small>{note}</small>
          </article>
        ))}
      </section>
      {totals.missingCostLines > 0 && <p className="notice warn">Có {totals.missingCostLines} dòng hàng thiếu giá vốn. Lãi gộp của kỳ này chưa tính được đầy đủ.</p>}
      <div className="overview-columns">
        <section className="panel overview-panel" aria-label="Xu hướng doanh số">
          <header className="overview-panel-heading">
            <div><h2>Xu hướng doanh số</h2><p className="muted">Theo ngày giao thành công{bucketSize > 1 ? ` · Gộp tối đa ${bucketSize} ngày mỗi cột` : ""}</p></div>
            <div className="overview-metric-toggle" role="group" aria-label="Chỉ số biểu đồ">
              <button type="button" className="small" aria-pressed={metric === "merchandise"} onClick={() => setMetric("merchandise")}>Doanh thu</button>
              <button type="button" className="small" aria-pressed={metric === "orders"} onClick={() => setMetric("orders")}>Đã giao</button>
            </div>
          </header>
          <div className="overview-chart-readout" aria-live="polite"><span>{dayRange(selected.start, selected.end)}</span><strong>{formatMetric(selected[metric])}</strong></div>
          <div className="overview-chart-scroll">
            <div className="overview-chart" style={{ gridTemplateColumns: `repeat(${buckets.length}, minmax(38px, 1fr))` }}>
              {buckets.map((bucket) => (
                <button type="button" key={bucket.start} className="overview-chart-column" aria-pressed={bucket.start === selected.start} title={`${dayRange(bucket.start, bucket.end)} · ${formatMetric(bucket[metric])}`} aria-label={`${dayRange(bucket.start, bucket.end)}, ${formatMetric(bucket[metric])}`} onClick={() => setSelectedDay(bucket.start)}>
                  <span className="overview-bar-track" aria-hidden="true"><span className="overview-chart-bar" style={{ height: `${100 * Number(bucket[metric]) / peak}%` }} /></span>
                  <small aria-hidden="true">{dateLabel(bucket.start)}</small>
                </button>
              ))}
            </div>
          </div>
          {!totals.orders && <p className="overview-chart-empty muted">Chưa có đơn giao thành công trong kỳ này.</p>}
        </section>
        <section className="panel overview-panel" aria-labelledby="overview-order-status">
          <header className="overview-panel-heading"><div><h2 id="overview-order-status">Trạng thái đơn hàng</h2><p className="muted">Trạng thái hiện tại của đơn tạo trong kỳ</p></div></header>
          {data.statuses.length ? <ul className="overview-status-list">
            {data.statuses.map(({ status, count }) => (
              <li key={status}>
                <div><span className={"status " + status}>{statusLabels[status] ?? status}</span><strong>{number.format(count)}</strong></div>
                <span className="overview-status-track" aria-hidden="true"><span style={{ width: `${100 * count / totals.createdOrders}%` }} /></span>
              </li>
            ))}
          </ul> : <p className="overview-chart-empty muted">Chưa có đơn hàng được tạo trong kỳ này.</p>}
        </section>
      </div>
      <section className="panel overview-panel" aria-labelledby="overview-product-title">
        <header className="overview-panel-heading"><div><h2 id="overview-product-title">Sản phẩm dẫn đầu doanh thu</h2><p className="muted">Tối đa 10 dòng theo doanh thu từ các đơn đã giao</p></div></header>
        {data.topProducts.length ? <div className="table-scroll overview-product-table" tabIndex={0} aria-label="Bảng doanh thu theo sản phẩm">
          <table>
            <thead><tr><th scope="col">Sản phẩm</th><th scope="col">Đã giao</th><th scope="col">Doanh thu hàng</th><th scope="col">Lãi gộp</th></tr></thead>
            <tbody>{data.topProducts.map((product) => (
              <tr key={`${product.productId}:${product.unit}`}>
                <th scope="row">{product.name}</th>
                <td>{number.format(Number(product.quantity))} {product.unit}</td>
                <td className="money">{money(product.merchandise)}</td>
                <td>{product.grossProfit === null ? "Chưa đủ dữ liệu" : money(product.grossProfit)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div> : <p className="overview-chart-empty muted">Chưa có sản phẩm được giao trong kỳ này.</p>}
      </section>
      <section className="panel overview-panel" aria-labelledby="overview-sales-detail">
        <header className="overview-panel-heading"><div><h2 id="overview-sales-detail">Chi tiết doanh số</h2><p className="muted">Tính trên các đơn giao thành công trong kỳ</p></div></header>
        <dl className="overview-sales-detail">
          <div><dt>Giá trị đơn trung bình</dt><dd>{totals.averageOrderValue === null ? "—" : money(totals.averageOrderValue)}</dd></div>
          <div><dt>Giá vốn</dt><dd>{totals.cost === null ? "Chưa đủ dữ liệu" : money(totals.cost)}</dd></div>
          <div><dt>Phí giao</dt><dd>{money(totals.shipping)}</dd></div>
          <div><dt>VAT</dt><dd>{money(totals.vat)}</dd></div>
          <div><dt>Doanh thu trước phí</dt><dd>{money(totals.merchandise)}</dd></div>
          <div><dt>Phí nền tảng</dt><dd>{money(totals.platformFees)}</dd></div>
          <div><dt>Doanh thu sau phí</dt><dd>{money(totals.afterPlatformFees)}</dd></div>
          <div><dt>Lãi sau phí</dt><dd>{totals.profitAfterFees === null ? "Chưa đủ dữ liệu" : money(totals.profitAfterFees)}</dd></div>
        </dl>
      </section>
    </div>
  );
}
