"use client";
import { useEffect, useRef, useState } from "react";
import type { MapPoint } from "./point-map";

let loader: Promise<any> | undefined;
function loadGoogle(key: string): Promise<any> {
  if (!key) return Promise.reject(new Error("Chưa cấu hình key bản đồ website."));
  if ((window as any).google?.maps) return Promise.resolve((window as any).google.maps);
  if (!loader) {
    loader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(key);
      script.async = true;
      script.onload = () => (window as any).google?.maps ? resolve((window as any).google.maps) : reject(new Error("Không tải được Google Maps."));
      script.onerror = () => reject(new Error("Không tải được Google Maps. Kiểm tra kết nối và key."));
      document.head.appendChild(script);
    }).catch(error => { loader = undefined; throw error; });
  }
  return loader;
}

export default function GooglePointMap({ value, center, browserKey, onChange, disabled }: {
  value: MapPoint | null; center: MapPoint; browserKey: string;
  onChange: (point: MapPoint) => void; disabled: boolean;
}) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const marker = useRef<any>(null);
  const latest = useRef({ onChange, disabled });
  latest.current = { onChange, disabled };
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    loadGoogle(browserKey).then(maps => {
      if (stopped || !element.current) return;
      const initial = value ?? center;
      const instance = new maps.Map(element.current, {
        center: { lat: initial.latitude, lng: initial.longitude }, zoom: 16, streetViewControl: false,
      });
      const pin = new maps.Marker({ map: instance, draggable: true });
      map.current = instance;
      marker.current = pin;
      const changed = (latLng: any) => {
        if (!latLng || latest.current.disabled) return;
        latest.current.onChange({ latitude: latLng.lat(), longitude: latLng.lng() });
      };
      instance.addListener("click", (event: any) => changed(event.latLng));
      pin.addListener("dragend", (event: any) => changed(event.latLng));
      if (value) pin.setPosition({ lat: value.latitude, lng: value.longitude });
      else pin.setVisible(false);
      setReady(true);
    }).catch(e => { if (!stopped) setError(e.message); });
    return () => { stopped = true; marker.current?.setMap(null); marker.current = null; map.current = null; };
  }, [browserKey]);
  useEffect(() => {
    if (!ready || !marker.current) return;
    marker.current.setDraggable(!disabled);
    marker.current.setVisible(!!value);
    if (value) {
      const position = { lat: value.latitude, lng: value.longitude };
      marker.current.setPosition(position);
      map.current?.panTo(position);
    }
  }, [value, disabled, ready]);
  return <div className="point-map">
    <p className="muted">Bấm hoặc kéo ghim đến điểm nhận, sau đó xác nhận vị trí.</p>
    <div ref={element} className="point-map-canvas" role="region" aria-label="Bản đồ chọn điểm nhận" tabIndex={0} />
    {!ready && !error && <p role="status">Đang tải bản đồ…</p>}
    {error && <p className="notice warn" role="alert">{error}</p>}
    <button type="button" disabled={!ready || disabled} onClick={() => {
      const center = map.current?.getCenter();
      if (center) latest.current.onChange({ latitude: center.lat(), longitude: center.lng() });
    }}>Chọn điểm ở tâm bản đồ</button>
  </div>;
}
