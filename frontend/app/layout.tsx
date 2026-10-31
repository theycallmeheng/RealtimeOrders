import type { Metadata } from "next";
import { config } from "@fortawesome/fontawesome-svg-core";
import "@fortawesome/fontawesome-svg-core/styles.css";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import "./visual-theme.css";
import "./motion.css";
config.autoAddCss = false;
export const metadata: Metadata = {
  title: "RealtimeOrders · Đặt hàng trong ngày",
  description:
    "Đặt hàng, duyệt kho và điều phối giao hàng theo thời gian thực.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
