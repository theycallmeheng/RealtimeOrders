"use client";
import { useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, Marker } from "leaflet";

export type MapPoint = { latitude: number; longitude: number };
export default function PointMap({ value, center, tileUrl, onChange, disabled = false }: {
  value: MapPoint | null; center: MapPoint; tileUrl: string;
  onChange: (point: MapPoint) => void; disabled?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap | null>(null);
  const marker = useRef<Marker | null>(null);
  const latest = useRef({ value, center, onChange, disabled });
  latest.current = { value, center, onChange, disabled };
  const [ready, setReady] = useState(false);
  const [tilesReady, setTilesReady] = useState(false);
  const [error, setError] = useState("");
  const placeMarker = useRef<(point: MapPoint) => void>(() => {});
  useEffect(() => {
    let cancelled = false;
    let observer: ResizeObserver | undefined;
    import("leaflet").then((L) => {
      if (cancelled || !container.current) return;
      const start = latest.current.value ?? latest.current.center;
      const instance = L.map(container.current, { scrollWheelZoom: false }).setView([start.latitude, start.longitude], 16);
      map.current = instance;
      L.tileLayer(tileUrl, { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors' })
        .on("tileload", () => { if (!cancelled) setTilesReady(true); })
        .on("tileerror", () => { if (!cancelled) setError("Một phần bản đồ chưa tải được. Kiểm tra mạng và phóng to để kiểm tra đúng vị trí."); }).addTo(instance);
      const changed = (lat: number, lng: number) => {
        if (latest.current.disabled) return;
        const point = { latitude: Number(lat.toFixed(7)), longitude: Number(lng.toFixed(7)) };
        placeMarker.current(point);
        latest.current.onChange(point);
      };
      placeMarker.current = (point) => {
        if (marker.current) marker.current.setLatLng([point.latitude, point.longitude]);
        else marker.current = L.marker([point.latitude, point.longitude], {
          draggable: !latest.current.disabled, keyboard: true, title: "Điểm nhận đã chọn", alt: "Điểm nhận đã chọn",
          icon: L.divIcon({ className: "point-map-pin", html: '<span class="point-map-dot"></span>', iconSize: [28, 34], iconAnchor: [14, 32] }),
        }).on("dragend", () => { const pos = marker.current!.getLatLng(); changed(pos.lat, pos.lng); }).addTo(instance);
      };
      if (latest.current.value) placeMarker.current(latest.current.value);
      instance.on("click", (event) => changed(event.latlng.lat, event.latlng.lng));
      observer = new ResizeObserver(() => instance.invalidateSize());
      observer.observe(container.current);
      setReady(true);
    }).catch(() => { if (!cancelled) setError("Không tải được bản đồ. Hãy tải lại trang."); });
    return () => { cancelled = true; observer?.disconnect(); map.current?.remove(); map.current = null; marker.current = null; };
  }, [tileUrl]);
  useEffect(() => {
    if (!ready || !map.current) return;
    if (value) {
      placeMarker.current(value);
      if (!map.current.getBounds().contains([value.latitude, value.longitude])) map.current.setView([value.latitude, value.longitude], 17);
    } else if (marker.current) { marker.current.remove(); marker.current = null; }
  }, [value, ready]);
  useEffect(() => { if (disabled) marker.current?.dragging?.disable(); else marker.current?.dragging?.enable(); }, [disabled, ready]);
  return <div className="point-map">
    <p className="muted">Phóng to, bấm đúng cổng/số nhà hoặc kéo ghim đến điểm nhận. Điểm này được dùng để tính quãng đường.</p>
    <div ref={container} className="point-map-canvas" role="region" aria-label="Bản đồ chọn điểm nhận" tabIndex={0} />
    {(!ready || !tilesReady) && !error && <p role="status">Đang tải bản đồ…</p>}
    {error && <p className="notice warn" role="status">{error}</p>}
    <button type="button" disabled={!ready || disabled} onClick={() => {
      const pos = map.current?.getCenter();
      if (pos) latest.current.onChange({ latitude: Number(pos.lat.toFixed(7)), longitude: Number(pos.lng.toFixed(7)) });
    }}>Chọn điểm ở tâm bản đồ</button>
  </div>;
}
