"use client";

import { activityLabel, activityFields, changedFields } from "../lib/activity-labels";
import { tabForPath, pathForTab } from "../lib/navigation";
import { menuPrices } from "../lib/pricing";
import PointMap, { type MapPoint } from "./point-map";
import GooglePointMap from "./google-point-map";
import BusinessScreen, { ProductReviews, PostComments, PostReactions } from "./business-ui";
import OverviewDashboard, { type OverviewData } from "./overview";
import StockScreen from "./stock-ui";
import VatSettings from "./vat-settings";
import ProductRequests from "./product-requests";
import ExpandablePostText from "./expandable-post-text";
import { readCart } from "../lib/marketplace";
import React, {
  useState,
  useEffect,
  useCallback,
  useRef,
  createContext,
  useContext,
  FormEvent,
} from "react";
import { FontAwesomeIcon as Icon } from "@fortawesome/react-fontawesome";
import {
  faBasketShopping,
  faListCheck,
  faCommentDots,
  faBell,
  faLocationDot,
  faSliders,
  faUsers,
  faChartColumn,
  faBoxOpen,
  faPlus,
  faArrowRightFromBracket,
  faRotate,
  faHeart,
  faImage,
  faTrash,
  faUser,
  faClipboardList,
  faCartShopping,
  faMagnifyingGlass,
  faVolumeHigh,
  faVolumeXmark,
} from "@fortawesome/free-solid-svg-icons";

type Row = Record<string, any>;
type Session = { user: Row; csrfToken: string; demo: boolean };
const TAB_STORAGE_KEY = "ro-tab-session";
const defaultTab = (session: Session) =>
  session.user.role === "CUSTOMER" ? "catalog" : "orders";
function restoreTab(session: Session) {
  const direct = tabForPath(session.user.role, window.location.pathname);
  if (direct) return direct;
  if (window.location.pathname !== "/") return defaultTab(session);
  const saved = sessionStorage.getItem(TAB_STORAGE_KEY);
  return saved && pathForTab(session.user.role, saved) ? saved : defaultTab(session);
}

class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: Row,
  ) {
    super(message);
  }
}
let csrfToken = "";
let activeRole = "";
// The catalog model follows the socket cursor. HTTP refreshes cannot overwrite
// a newer streamed state or race the snapshot/live boundary.
let datasetEpoch = "";
let catalogOwner = "";
let catalogModel: Row[] | null = null;
let followedProducts = new Set<string>();
const catalogChanged = () => window.dispatchEvent(new Event("ro:catalog"));
async function api(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
  signal?: AbortSignal,
): Promise<any> {
  if (activeRole === "SELLER" && path.startsWith("/admin/")) path = path.replace("/admin/", "/shop/");
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch("/api/v1" + path, {
    method,
    headers,
    signal,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new ApiError(
      result.error?.code ?? "ERROR",
      result.error?.message ?? "Không xử lý được yêu cầu",
      result.error?.details,
    );
  return result;
}
const money = (n: unknown) =>
  new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(
    /^-?\d+$/.test(String(n ?? 0)) ? BigInt(String(n ?? 0)) : Number(n ?? 0),
  );
function productImageSrc(image: unknown): string {
  let source = "";
  if (typeof image === "string") source = image;
  else if (image && typeof image === "object") {
    const item = image as Row;
    source = item.source_url ?? item.url ?? item.asset_id ?? "";
  }
  if (!source) return "";
  if (/^https:\/\//i.test(source) || source.startsWith("/")) return source;
  return "/api/v1/media/" + encodeURIComponent(source);
}
const qty = (n: unknown) =>
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 3 }).format(
    Number(n ?? 0),
  );
const lineMoney = (price: unknown, quantity: unknown) => {
  const [whole, fraction = ""] = String(quantity).split(".");
  const thousandths =
    BigInt(whole || "0") * BigInt(1000) +
    BigInt(fraction.padEnd(3, "0").slice(0, 3));
  return (BigInt(String(price)) * thousandths + BigInt(500)) / BigInt(1000);
};
const date = (n: string) => (n ? new Date(n).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "");
const statuses: Record<string, string> = {
  PENDING: "Chờ duyệt",
  APPROVED: "Đã duyệt",
  PREPARING: "Đang chuẩn bị",
  SHIPPING: "Đang giao",
  DELIVERED: "Đã giao",
  READY_FOR_PICKUP: "Sẵn sàng lấy hàng",
  DELIVERY_FAILED: "Giao chưa thành công",
  REJECTED: "Từ chối",
  CANCELLED: "Đã hủy",
  NEW: "Mới gửi",
  RECEIVED: "Đã tiếp nhận",
  QUOTED: "Đã báo giá",
  ACCEPTED: "Đã chấp thuận",
  CONVERTED: "Đã tạo đơn",
  OPEN: "Đang mở",
  CLOSED: "Đã đóng",
  EXPIRED: "Đã hết hạn",
  SCHEDULED: "Chờ giờ mở",
  SOLD_OUT: "Đã bán hết",
  DRAFT: "Bản nháp",
  ACTIVE: "Hoạt động",
  LOCKED: "Bị khóa",
  DELETED: "Đã xóa",
};
const Status = ({ value }: { value: string }) => (
  <span className={"status " + value}>{statuses[value] ?? value}</span>
);
const Empty = ({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) => (
  <div className="empty">
    <h3>{title}</h3>
    {children && <p>{children}</p>}
  </div>
);
function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const id = React.useId();
  const control = React.isValidElement(children)
    ? React.cloneElement(children as React.ReactElement<{ id?: string }>, {
        id,
      })
    : children;
  return (
    <div className={"field " + (wide ? "wide" : "")}>
      <label htmlFor={id}>{label}</label>
      {control}
    </div>
  );
}
function Modal({
  title,
  children,
  close,
  inline = false,
  docked = false,
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
  inline?: boolean;
  docked?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (inline || docked) return;
    const old = document.activeElement as HTMLElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const root = ref.current;
    const focusable = () =>
      Array.from(
        root?.querySelectorAll<HTMLElement>(
          'button,a[href],input,select,textarea,[tabindex="0"]',
        ) ?? [],
      ).filter((e) => !e.hasAttribute("disabled"));
    focusable()[0]?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const els = focusable();
        if (e.shiftKey && document.activeElement === els[0]) {
          e.preventDefault();
          els.at(-1)?.focus();
        } else if (!e.shiftKey && document.activeElement === els.at(-1)) {
          e.preventDefault();
          els[0]?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = oldOverflow;
      old?.focus();
    };
  }, [inline, docked]);
  if (docked)
    return (
      <aside className="modal" aria-label={title} onKeyDown={(e) => {
        if (e.key === "Escape") { e.stopPropagation(); close(); }
      }}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={close} aria-label="Đóng giỏ hàng">✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </aside>
    );
  if (inline)
    return (
      <div className="inline-modal" ref={ref} role="region" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    );
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={close} aria-label="Đóng">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
type Context = {
  session: Session;
  online: boolean;
  refresh: number;
  notify: (s: string, error?: boolean) => void;
  mutate: (path: string, body?: Row, method?: string) => Promise<any>;
  reload: () => void;
  setSession: React.Dispatch<React.SetStateAction<Session | null>>;
};
const AppContext = createContext<Context>(null!);
const useApp = () => useContext(AppContext);

export default function App() {
  const [session, setSession] = useState<Session | null>(null),
    [sessionCheck, setSessionCheck] = useState<"loading" | "ready" | "error">("loading"),
    [sessionAttempt, setSessionAttempt] = useState(0),
    [tab, setTab] = useState("catalog"),
    [online, setOnline] = useState(false),
    [refresh, setRefresh] = useState(0),
    [unreadChat, setUnreadChat] = useState(0),
    [soundEnabled, setSoundEnabled] = useState(true),
    [soundReady, setSoundReady] = useState(false),
    [customerNotice, setCustomerNotice] = useState<{ id: string; text: string } | null>(null),
    [messageNotice, setMessageNotice] = useState<{
      id: string;
      conversationId: string;
      title: string;
      preview: string;
    } | null>(null),
    [orderNotice, setOrderNotice] = useState<{
      id: string;
      orderId: string;
    } | null>(null),
    [toast, setToast] = useState<{ message: string; error: boolean } | null>(
      null,
    ),
    [pending, setPending] = useState<Row[]>([]);
  const [navCollapsed, setNavCollapsed] = useState(false),
    [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // Animate headings only: transforming main would move fixed dialogs/cart.
    const heading = document.querySelector("main .page-heading");
    const animation = heading?.animate(
      [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 240, easing: "ease-out" },
    );
    return () => animation?.cancel();
  }, [tab]);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  activeRole = session?.user.role ?? "";
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const soundEnabledRef = useRef(soundEnabled);
  soundEnabledRef.current = soundEnabled;
  const audioContextRef = useRef<AudioContext | null>(null);
  const soundReadyRef = useRef(false);
  const unlockNotificationSound = useCallback(async (): Promise<boolean> => {
    try {
      if (!audioContextRef.current) {
        if (!window.AudioContext) return false;
        audioContextRef.current = new window.AudioContext();
        audioContextRef.current.onstatechange = () => {
          const ready = audioContextRef.current?.state === "running";
          soundReadyRef.current = ready;
          setSoundReady(ready);
        };
      }
      const context = audioContextRef.current;
      if (context.state !== "running") await context.resume();
      const ready = context.state === "running";
      soundReadyRef.current = ready;
      setSoundReady(ready);
      return ready;
    } catch {
      soundReadyRef.current = false;
      setSoundReady(false);
      return false;
    }
  }, []);
  const playNotificationSound = useCallback(
    (preview = false, kind: "message" | "order" = "message") => {
      const context = audioContextRef.current;
      if ((!preview && !soundEnabledRef.current) || !context) return;
      const play = () => {
        if (context.state !== "running") return;
        const start = context.currentTime;
        const notes = kind === "order" ? [523, 659, 784] : [880, 1175];
        notes.forEach((frequency, index) => {
          const delay = index * (kind === "order" ? 0.12 : 0.14);
          const oscillator = context.createOscillator();
          const volume = context.createGain();
          const noteStart = start + delay;
          oscillator.type = "sine";
          oscillator.frequency.setValueAtTime(frequency, noteStart);
          volume.gain.setValueAtTime(0.0001, noteStart);
          volume.gain.exponentialRampToValueAtTime(0.17, noteStart + 0.02);
          volume.gain.exponentialRampToValueAtTime(0.0001, noteStart + 0.21);
          oscillator.connect(volume);
          volume.connect(context.destination);
          oscillator.start(noteStart);
          oscillator.stop(noteStart + 0.22);
        });
      };
      if (context.state === "running") play();
      else void context.resume().then(play).catch(() => {});
    },
    [],
  );
  const navigateTo = useCallback((target: string, replace = false) => {
    const active = sessionRef.current;
    if (!active) return;
    const path = pathForTab(active.user.role, target);
    if (!path) return;
    if (window.location.pathname !== path) {
      window.history[replace ? "replaceState" : "pushState"](null, "", path);
    }
    setTab(target);
    setNavOpen(false);
  }, []);
  useEffect(() => {
    setNavCollapsed(localStorage.getItem("ro-nav-collapsed") === "true");
    const navigate = (e: Event) => navigateTo((e as CustomEvent).detail);
    const pop = () => {
      const active = sessionRef.current;
      if (!active) return;
      const target = tabForPath(active.user.role, window.location.pathname);
      if (target) { setTab(target); setNavOpen(false); }
      else navigateTo(defaultTab(active), true);
    };
    window.addEventListener("ro:navigate", navigate);
    window.addEventListener("popstate", pop);
    return () => {
      window.removeEventListener("ro:navigate", navigate);
      window.removeEventListener("popstate", pop);
    };
  }, [navigateTo]);
  useEffect(() => {
    const unlock = () => unlockNotificationSound();
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
      if (audioContextRef.current) audioContextRef.current.onstatechange = null;
      void audioContextRef.current?.close();
      audioContextRef.current = null;
      soundReadyRef.current = false;
    };
  }, [unlockNotificationSound]);
  useEffect(() => {
    const enabled = localStorage.getItem("ro-notification-sound") !== "off";
    setSoundEnabled(enabled);
    soundEnabledRef.current = enabled;
  }, []);
  useEffect(() => {
    if (!session) return;
    const target = restoreTab(session);
    const path = pathForTab(session.user.role, target)!;
    window.history.replaceState(null, "", path);
    setTab(target);
  }, [session?.user.id]);
  useEffect(() => {
    if (session) sessionStorage.setItem(TAB_STORAGE_KEY, tab);
  }, [session?.user.id, tab]);
  useEffect(() => {
    if (tab === "chat") {
      setUnreadChat(0);
      setMessageNotice(null);
    }
  }, [tab]);
  useEffect(() => {
    setUnreadChat(0);
    setMessageNotice(null);
    setOrderNotice(null);
    setCustomerNotice(null);
  }, [session?.user.id]);
  useEffect(() => {
    if (!customerNotice) return;
    const timer = setTimeout(() => setCustomerNotice(null), 10000);
    return () => clearTimeout(timer);
  }, [customerNotice]);
  const notify = useCallback(
    (message: string, error = false) => setToast({ message, error }),
    [],
  );
  const reload = useCallback(() => setRefresh((x) => x + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    let active = true;
    api("/auth/session", "GET", undefined, undefined, controller.signal)
      .then((s) => {
        if (!active) return;
        csrfToken = s.csrfToken;
        setSession(s);
        setTab(restoreTab(s));
        setSessionCheck("ready");
      })
      .catch((error) => {
        if (!active) return;
        const signedOut = error instanceof ApiError &&
          (error.code === "AUTH_REQUIRED" || error.code === "SESSION_EXPIRED");
        setSessionCheck(signedOut ? "ready" : "error");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [sessionAttempt]);
  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(null), 7000);
      return () => clearTimeout(id);
    }
  }, [toast]);
  useEffect(() => {
    if (messageNotice) {
      const id = setTimeout(() => setMessageNotice(null), 8000);
      return () => clearTimeout(id);
    }
  }, [messageNotice]);
  useEffect(() => {
    if (orderNotice) {
      const id = setTimeout(() => setOrderNotice(null), 10000);
      return () => clearTimeout(id);
    }
  }, [orderNotice]);
  useEffect(() => {
    if (!session) return;
    try {
      setPending(
        JSON.parse(
          sessionStorage.getItem("ro-pending-" + session.user.id) ?? "[]",
        ),
      );
    } catch {
      setPending([]);
    }
  }, [session?.user.id]);
  const savePending = useCallback((list: Row[]) => {
    setPending(list);
    const id = sessionRef.current?.user.id;
    if (id) sessionStorage.setItem("ro-pending-" + id, JSON.stringify(list));
  }, []);
  const mutate = useCallback(
    async (path: string, body: Row = {}, method = "POST") => {
      const key = crypto.randomUUID(),
        entry = { key, path, body, method };
      const removePending = () => {
        let current: Row[] = [];
        try {
          current = JSON.parse(
            sessionStorage.getItem(
              "ro-pending-" + sessionRef.current!.user.id,
            ) ?? "[]",
          );
        } catch {}
        savePending(current.filter((x) => x.key !== key));
      };
      const durable =
        path === "/orders" ||
        /\/product-requests(?:\/|$)/.test(path) ||
        /^\/(feed|admin\/menus)\/[^/]+\/(comments|reactions)$/.test(path) ||
        /^\/((admin|shop|courier)\/)?orders\//.test(path) ||
        /^\/(admin\/refunds|shop\/money)\//.test(path) ||
        /^\/admin\/(stock|supplier-payments)\//.test(path) ||
        path === "/admin/products/bulk" ||
        /\/convert$/.test(path) ||
        /\/messages$/.test(path);
      let list: Row[] = [];
      if (durable) {
        try {
          list = JSON.parse(
            sessionStorage.getItem(
              "ro-pending-" + sessionRef.current!.user.id,
            ) ?? "[]",
          );
        } catch {}
        savePending([...list, entry]);
      }
      try {
        const result = await api(path, method, body, key);
        if (durable) removePending();
        reload();
        return result;
      } catch (e) {
        if (e instanceof ApiError) {
          if (durable && !["RETRY_REQUIRED", "INTERNAL_ERROR"].includes(e.code))
            removePending();
          if (e.code === "SESSION_EXPIRED" || e.code === "AUTH_REQUIRED")
            setSession(null);
          if (
            [
              "VERSION_CONFLICT",
              "REQUOTE_REQUIRED",
              "INSUFFICIENT_STOCK",
              "MENU_STOCK_EXCEEDED",
              "PAYMENT_EXCEEDS_DEBT",
              "SOLD_OUT",
            ].includes(e.code)
          )
            reload();
        }
        notify(
          e instanceof Error
            ? e.message
            : "Kết nối bị gián đoạn; giữ mã yêu cầu để gửi lại.",
          true,
        );
        throw e;
      }
    },
    [notify, reload, savePending],
  );
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    if (catalogOwner !== session.user.id) {
      catalogOwner = session.user.id;
      catalogModel = null;
      followedProducts = new Set();
    }
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    let attempt = 0;
    let model = false;
    let chunks: string[] = [];
    const heads: Record<string, string> = {};
    let refreshTimer: ReturnType<typeof setTimeout>;
    let lastActivity = 0;
    let lastServerMessage = Date.now();
    const scheduleRefresh = () => {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(reload, 120);
    };
    const connect = () => {
      if (!navigator.onLine) {
        setOnline(false);
        timer = setTimeout(connect, 2000);
        return;
      }
      if (
        socket &&
        (socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING)
      )
        return;
      lastServerMessage = Date.now();
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`,
      );
      socket.onopen = () =>
        socket?.send(
          JSON.stringify({
            v: 1,
            type: "HELLO",
            hasModel: model,
            datasetEpoch,
            lastSeq: heads,
          }),
        );
      socket.onmessage = (e) => {
        lastServerMessage = Date.now();
        let m: Row;
        try {
          m = JSON.parse(e.data);
        } catch {
          return;
        }
        if (m.type === "PING") {
          socket?.send(JSON.stringify({ v: 1, type: "PONG" }));
          return;
        }
        if (m.type === "SYNC_BEGIN") {
          setOnline(false);
          chunks = [];
        }
        if (m.type === "SNAPSHOT_CHUNK") chunks[m.index] = m.data;
        if (m.type === "SYNC_END") {
          datasetEpoch = m.datasetEpoch ?? "";
          if (chunks.length) {
            try {
              const snapshot = JSON.parse(chunks.join(""));
              catalogModel = snapshot.offers;
              followedProducts = new Set(
                (snapshot.subscriptions ?? []).map((s: Row) => s.product_id),
              );
              catalogChanged();
              model = true;
            } catch {
              socket?.send(
                JSON.stringify({
                  v: 1,
                  type: "RESYNC_REQUEST",
                  hasModel: false,
                }),
              );
              return;
            }
          }
          Object.assign(heads, m.heads);
          attempt = 0;
          setOnline(true);
          scheduleRefresh();
        }
        if (m.type === "SESSION_REVOKED") {
          notify(m.message ?? "Phiên đã bị thu hồi.", true);
          setSession(null);
          return;
        }
        if (m.type === "EVENT") {
          const last = BigInt(heads[m.topic] ?? "0"),
            seq = BigInt(m.seq);
          if (seq <= last) return;
          if (model && seq > last + BigInt(1)) {
            socket?.send(
              JSON.stringify({ v: 1, type: "RESYNC_REQUEST", hasModel: false }),
            );
            setOnline(false);
            return;
          }
          heads[m.topic] = m.seq;
          if (m.eventType === "CONTENT_WARNING")
            notify(m.payload.message, true);
          if (m.eventType === "MODERATION_WARNING")
            notify(
              "Có nội dung vi phạm mới. Xem Nhật ký → Vi phạm nội dung.",
              true,
            );
          if (m.eventType === "NOTIFICATION" && m.payload?.kind !== "CHAT_MESSAGE") {
            setCustomerNotice({ id: String(m.payload?.id ?? crypto.randomUUID()), text: String(m.payload?.payload?.message ?? "Bạn có thông báo mới.") });
            playNotificationSound();
          }
          if (
            m.eventType === "CHAT_MESSAGE" &&
            m.payload?.sender_id !== sessionRef.current?.user.id
          ) {
            const payload = m.payload ?? {};
            const text = String(payload.text_sanitized ?? "").trim();
            const hasAttachments =
              Array.isArray(payload.attachments) && payload.attachments.length > 0;
            const preview =
              text || (hasAttachments ? "Đã gửi ảnh" : "Có tin nhắn mới.");
            setMessageNotice({
              id: crypto.randomUUID(),
              conversationId: String(payload.conversation_id ?? ""),
              title:
                ["ADMIN","SELLER"].includes(sessionRef.current?.user.role ?? "")
                  ? "Tin nhắn mới từ khách hàng"
                  : "Người bán vừa nhắn tin",
              preview:
                preview.length > 120 ? preview.slice(0, 117) + "…" : preview,
            });
            playNotificationSound();
            if (tabRef.current !== "chat")
              setUnreadChat((count) => Math.min(99, count + 1));
          }
          if (
            m.eventType === "ORDER_CHANGED" &&
            m.payload?.status === "PENDING" &&
            ["ADMIN","SELLER"].includes(sessionRef.current?.user.role ?? "")
          ) {
            playNotificationSound(false, "order");
            setOrderNotice({
              id: crypto.randomUUID(),
              orderId: String(m.payload.id ?? ""),
            });
          }
          if (
            m.eventType === "CATALOG_CHANGED" &&
            Array.isArray(m.payload.offers)
          ) {
            const next = new Map(
              (catalogModel ?? [])
                .filter((o) => !m.payload.removedOfferIds.includes(o.id))
                .map((o) => [o.id, o]),
            );
            for (const offer of m.payload.offers)
              next.set(offer.id, {
                ...offer,
                subscribed: followedProducts.has(offer.product_id),
              });
            catalogModel = [...next.values()].sort((a, b) =>
              a.name.localeCompare(b.name, "vi"),
            );
            catalogChanged();
            return;
          }
          if (m.eventType === "CATALOG_CHANGED" && m.payload.refresh) {
            setOnline(false);
            socket?.send(
              JSON.stringify({ v: 1, type: "RESYNC_REQUEST", hasModel: false }),
            );
            return;
          }
          if (m.eventType === "SUBSCRIPTION_CHANGED") {
            if (m.payload.enabled) followedProducts.add(m.payload.productId);
            else followedProducts.delete(m.payload.productId);
            catalogModel =
              catalogModel?.map((o) => ({
                ...o,
                subscribed: followedProducts.has(o.product_id),
              })) ?? null;
            catalogChanged();
            return;
          }
          scheduleRefresh();
        }
      };
      socket.onerror = () => setOnline(false);
      socket.onclose = (e) => {
        setOnline(false);
        if (!stopped) {
          if (e.code === 1008) {
            api("/auth/session").catch(() => setSession(null));
          }
          timer = setTimeout(
            connect,
            Math.min(15000, 1000 * 2 ** attempt++) + Math.random() * 400,
          );
        }
      };
    };
    connect();
    const activity = () => {
      if (
        socket?.readyState === WebSocket.OPEN &&
        Date.now() - lastActivity > 20000
      ) {
        lastActivity = Date.now();
        socket.send(JSON.stringify({ v: 1, type: "SESSION_ACTIVITY" }));
      }
    };
    document.addEventListener("pointerdown", activity);
    document.addEventListener("keydown", activity);
    const offline = () => {
      setOnline(false);
      socket?.close();
    };
    const backOnline = () => {
      clearTimeout(timer);
      connect();
    };
    window.addEventListener("offline", offline);
    window.addEventListener("online", backOnline);
    const watchdog = setInterval(() => {
      if (
        socket?.readyState === WebSocket.OPEN &&
        Date.now() - lastServerMessage > 45000
      ) {
        setOnline(false);
        socket.close();
      }
    }, 5000);
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(refreshTimer);
      clearInterval(watchdog);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", backOnline);
      socket?.close();
      document.removeEventListener("pointerdown", activity);
      document.removeEventListener("keydown", activity);
    };
  }, [session?.user.id, notify, reload]);
  const retry = async () => {
    let left = [...pending];
    for (const e of pending) {
      try {
        const result = await api(e.path, e.method, e.body, e.key);
        if (e.path === "/orders") {
          const storageKey = "ro-daily-cart-" + sessionRef.current!.user.id;
          sessionStorage.removeItem(storageKey);
        }
        window.dispatchEvent(
          new CustomEvent("ro:operation-resolved", {
            detail: { path: e.path, result },
          }),
        );
        notify("Đã nhận kết quả thao tác trước đó.");
        left = left.filter((x) => x.key !== e.key);
        savePending(left);
      } catch (error) {
        if (
          error instanceof ApiError &&
          !["RETRY_REQUIRED", "INTERNAL_ERROR"].includes(error.code)
        ) {
          left = left.filter((x) => x.key !== e.key);
          savePending(left);
        }
        notify(
          error instanceof Error ? error.message : "Vẫn chưa kết nối được",
          true,
        );
        break;
      }
    }
    reload();
  };
  if (sessionCheck === "loading")
    return <div className="spinner" role="status">Đang kiểm tra phiên đăng nhập…</div>;
  if (sessionCheck === "error")
    return (
      <main className="auth-form">
        <div className="auth-inner">
          <h2>Chưa kiểm tra được phiên đăng nhập</h2>
          <p role="alert">Kiểm tra kết nối mạng rồi thử lại.</p>
          <button type="button" className="primary" onClick={() => {
            setSessionCheck("loading");
            setSessionAttempt((attempt) => attempt + 1);
          }}>Thử lại</button>
        </div>
      </main>
    );
  const actionToast = toast && (
    <div role="alert" className={"toast " + (toast.error ? "error" : "")}>
      <span>{toast.message}</span>
      <button
        className="ghost"
        onClick={() => setToast(null)}
        aria-label="Đóng thông báo thao tác"
      >
        ✕
      </button>
    </div>
  );
  if (!session)
    return (
      <>
        <Auth
          onLogin={(s) => {
            sessionStorage.removeItem(TAB_STORAGE_KEY);
            csrfToken = s.csrfToken;
            setSession(s);
            setTab(restoreTab(s));
          }}
        />
        {actionToast && <div className="live-notifications live-notifications-guest">{actionToast}</div>}
      </>
    );
  const seller = session.user.role === "SELLER";
  const admin = session.user.role === "ADMIN" || seller;
  const nav = session.user.role === "SHIPPER" ? [["orders", "Đơn được giao", faListCheck], ["notifications", "Thông báo", faBell]] : seller
    ? [
        ["orders", "Xử lý đơn", faListCheck],
        ["offers", "Menu theo ngày", faBasketShopping],
        ["products", "Sản phẩm", faBoxOpen],
        ["stock", "Kho và nhà cung cấp", faBoxOpen],
        ["requests", "Yêu cầu sản phẩm", faClipboardList],
        ["chat", "Tin nhắn khách", faCommentDots],
        ["reviews", "Đánh giá", faListCheck],
      ]
    : admin ? [
        ["reports", "Tổng quan", faChartColumn],
        ["orders", "Xử lý đơn", faListCheck],
        ["offers", "Menu theo ngày", faBasketShopping],
        ["products", "Sản phẩm", faBoxOpen],
        ["stock", "Kho và nhà cung cấp", faBoxOpen],
        ["requests", "Yêu cầu sản phẩm", faClipboardList],

        ["chat", "Tin nhắn", faCommentDots],
        ["users", "Khách hàng", faUsers],
        ["config", "Cấu hình", faSliders],
        ["audit", "Nhật ký", faListCheck],
        ["shop", "Hồ sơ cửa hàng", faBoxOpen],
        ["finance", "Thu / hoàn tiền", faChartColumn],
        ["staff", "Nhân viên", faUsers],
        ["reviews", "Đánh giá", faListCheck],
      ]
    : [
        ["feed", "Bảng tin cửa hàng", faBoxOpen],
        ["catalog", "Hàng trong ngày", faBasketShopping],
        ["checkout", "Giỏ hàng", faCartShopping],
        ["orders", "Đơn của tôi", faListCheck],
        ["requests", "Yêu cầu sản phẩm", faClipboardList],

        ["chat", "Nhắn người bán", faCommentDots],

        ["profile", "Hồ sơ & địa chỉ", faUser],
      ];
  const navGroups: { label: string; items: typeof nav }[] = session.user.role === "ADMIN"
    ? [
        { label: "Điều hành", items: nav.slice(0, 6) },
        { label: "Phục vụ khách", items: nav.slice(6, 9) },
        { label: "Quản trị", items: nav.slice(9) },
      ]
    : seller
      ? [
          { label: "Bán hàng", items: nav.slice(0, 5) },
          { label: "Kết nối khách", items: nav.slice(5) },
        ]
      : session.user.role === "SHIPPER"
        ? [{ label: "Nhiệm vụ", items: nav }]
        : [
            { label: "Mua sắm", items: nav.slice(0, 5) },
            { label: "Tài khoản", items: nav.slice(5) },
          ];
  return (
    <AppContext.Provider
      value={{
        session,
        online: online && pending.length === 0,
        refresh,
        notify,
        mutate,
        reload,
        setSession,
      }}
    >
      <header className="app-header">
        <a className="skip-link" href="#main-content">Đến nội dung chính</a>
        <button
          className="ghost nav-toggle"
          aria-label="Đóng mở thanh điều hướng"
          aria-expanded={navOpen || !navCollapsed}
          onClick={() => {
            if (window.innerWidth <= 760) setNavOpen(!navOpen);
            else {
              setNavCollapsed(!navCollapsed);
              localStorage.setItem("ro-nav-collapsed", String(!navCollapsed));
            }
          }}
        >
          ☰
        </button>
        <div className="brand">
          <span className="brand-mark">
            <Icon icon={faBasketShopping} />
          </span>
          <span className="brand-copy">RealtimeOrders<small>Thực phẩm cho mỗi ngày</small></span>
        </div>
        <div className="header-meta">
          <span className="connection" role="status">
            <i className={"dot " + (online ? "online" : "")} />
            {online ? "Đang đồng bộ" : "Đang kết nối lại"}
          </span>
          <button
            className="ghost notification-sound-toggle"
            aria-label={
              soundEnabled && soundReady
                ? "Tắt âm thanh thông báo"
                : soundEnabled
                  ? "Kích hoạt âm thanh thông báo"
                  : "Bật âm thanh thông báo"
            }
            aria-pressed={soundEnabled}
            title={
              soundEnabled
                ? soundReady
                  ? "Âm thanh thông báo đang bật · nhấn để tắt"
                  : "Nhấn để kích hoạt âm thanh thông báo"
                : "Nhấn để bật âm thanh thông báo"
            }
            onClick={async () => {
              if (
                soundEnabled &&
                soundReady &&
                audioContextRef.current?.state === "running"
              ) {
                setSoundEnabled(false);
                soundEnabledRef.current = false;
                localStorage.setItem("ro-notification-sound", "off");
                return;
              }
              setSoundEnabled(true);
              soundEnabledRef.current = true;
              localStorage.setItem("ro-notification-sound", "on");
              if (!(await unlockNotificationSound()))
                notify(
                  "Trình duyệt chưa cho phép phát âm thanh. Hãy kiểm tra chế độ im lặng và âm lượng thiết bị.",
                  true,
                );
            }}
          >
            <Icon icon={soundEnabled ? faVolumeHigh : faVolumeXmark} />
            <span className="notification-sound-label">
              {!soundEnabled
                ? "Âm báo tắt"
                : soundReady
                  ? "Âm báo bật"
                  : "Kích hoạt âm báo"}
            </span>
          </button>
          <button
            className="ghost"
            aria-label="Thông báo"
            onClick={() => navigateTo("notifications")}
          >
            <Icon icon={faBell} />
          </button>
          <span className="user-name">
            <span className="user-avatar" aria-hidden="true">{String(session.user.display_name).trim().split(/\s+/).at(-1)?.charAt(0)}</span>
            <span>{session.user.display_name}<small>{{ADMIN:"Người quản trị",SELLER:"Người bán",SHIPPER:"Người giao hàng",CUSTOMER:"Khách hàng"}[session.user.role as string]}</small></span>
          </span>
          <button
            className="ghost"
            aria-label="Đăng xuất"
            onClick={async () => {
              try {
                await api("/auth/logout", "POST", {});
                csrfToken = "";
                sessionStorage.removeItem(TAB_STORAGE_KEY);
                sessionStorage.removeItem("ro:menu-promo-dismissed:" + session.user.id);
                window.history.replaceState(null, "", "/login");
                setSession(null);
              } catch (e) {
                notify((e as Error).message, true);
              }
            }}
          >
            <Icon icon={faArrowRightFromBracket} />
          </button>
        </div>
      </header>
      {session.user.role === "CUSTOMER" && <nav className="food-mobile-nav" aria-label="Điều hướng mua hàng">
        {[["catalog","Mua hàng",faBasketShopping],["checkout","Giỏ hàng",faCartShopping],["orders","Đơn hàng",faListCheck],["profile","Tài khoản",faUser]].map(([id,label,icon]) =>
          <a key={String(id)} href={pathForTab("CUSTOMER",String(id))} aria-current={tab===id?"page":undefined}
            onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; e.preventDefault(); navigateTo(String(id)); }}>
            <Icon icon={icon as any} /><span>{String(label)}</span>
          </a>)}
      </nav>}
      {navOpen && (
        <button
          className="nav-scrim"
          aria-label="Đóng menu"
          onClick={() => setNavOpen(false)}
        />
      )}
      <div
        className={
          "shell role-" + session.user.role.toLowerCase() +
          (navCollapsed ? " nav-collapsed" : "") +
          (navOpen ? " nav-open" : "")
        }
      >
        <aside className="nav">
          <div className="nav-label">
            {seller ? "Kênh người bán" : admin ? "Quản trị cửa hàng" : session.user.role === "SHIPPER" ? "Giao nhận hàng" : "Cửa hàng của bạn"}
          </div>
          {navGroups.map((group) => {
            const items = group.items.filter(([id]) => !!pathForTab(session.user.role, String(id)));
            if (!items.length) return null;
            return <section className="nav-group" aria-label={group.label} key={group.label}>
              <h2 className="nav-group-title">{group.label}</h2>
              {items.map(([id, label, icon]) => (
                <a
                  key={String(id)}
                  href={pathForTab(session.user.role, String(id))}
                  aria-current={tab === id ? "page" : undefined}
                  className={tab === id ? "active" : ""}
                  title={String(label)}
                  aria-label={String(label)}
                  onClick={(event) => {
                    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
                    event.preventDefault();
                    navigateTo(String(id));
                  }}
                >
                  <Icon icon={icon as any} />
                  <span className="nav-title">{String(label)}</span>
                  {id === "chat" && unreadChat > 0 && (
                    <span className="nav-badge" aria-label={`${unreadChat} tin nhắn chưa đọc`}>
                      {unreadChat > 9 ? "9+" : unreadChat}
                    </span>
                  )}
                </a>
              ))}
            </section>;
          })}
          <div className="nav-foot">
            Nhóm 15 · Lập trình mạng
            <br />
            Dữ liệu lưu trên máy chủ
          </div>
        </aside>
        <main id="main-content" tabIndex={-1} data-role={session.user.role} data-screen={tab}>
          {session.demo && (
            <div className="notice warn demo-notice">
              Môi trường học tập · không dùng để bán hàng thật.
            </div>
          )}
          {!online && (
            <div className="notice warn">
              Đang khôi phục kết nối. Bạn vẫn xem được dữ liệu; thao tác mới mở
              lại khi đồng bộ xong.
            </div>
          )}
          {pending.length > 0 && (
            <div className="notice warn">
              Có {pending.length} thao tác chưa nhận được kết quả.{" "}
              <button className="small" disabled={!online} onClick={retry}>
                Kiểm tra và gửi lại
              </button>
            </div>
          )}
          {(tab === "catalog" || tab === "checkout") && (
            <DailyCatalog mode={tab === "checkout" ? "checkout" : "catalog"} />
          )}
          {["orders","feed","shop","staff","finance","reviews"].includes(tab) && <BusinessScreen kind={tab} user={session.user} online={online && pending.length===0} refresh={refresh} request={api} mutate={mutate} navigate={navigateTo} />}{" "}
          {tab === "stock" && <StockScreen user={session.user} online={online && pending.length===0} refresh={refresh} request={api} mutate={mutate} navigate={navigateTo} />}
          {tab === "shop" && seller && <WarehouseSettings />}
          {tab === "chat" && <Chat admin={admin} />}{" "}
          {tab === "notifications" && <Notifications />}{" "}
          {tab === "requests" && <ProductRequests kind="requests" user={session.user} online={online && pending.length === 0} refresh={refresh} request={api} mutate={mutate} navigate={navigateTo} />}
          {tab === "profile" && <Profile />}{" "}
          {tab === "offers" && <DailyMenus />}{" "}
          {tab === "products" && <Products />} {tab === "users" && <Users />}{" "}
          {tab === "config" && session.user.role === "ADMIN" && <>
            <VatSettings user={session.user} online={online && pending.length===0} refresh={refresh} request={api} mutate={mutate} navigate={navigateTo} />
            <Configuration />
          </>}{" "}
          {tab === "reports" && <Overview />} {tab === "audit" && <Audit />}
        </main>
      </div>
      {(messageNotice || orderNotice || customerNotice || toast) && (
        <div className="live-notifications">
          {customerNotice && (
            <div key={customerNotice.id} className="message-notice" role="status" aria-live="polite">
              <span className="message-notice-icon" aria-hidden="true"><Icon icon={faBell} /></span>
              <button className="message-notice-content" onClick={() => { setCustomerNotice(null); navigateTo("notifications"); }}>
                <strong>Thông báo mới</strong><span>{customerNotice.text}</span><small>Nhấn để xem thông báo</small>
              </button>
              <button className="ghost message-notice-close" aria-label="Đóng thông báo" onClick={() => setCustomerNotice(null)}>✕</button>
            </div>
          )}
          {orderNotice && (
            <div
              key={orderNotice.id}
              className="order-notice"
              role="status"
              aria-live="polite"
            >
              <span className="order-notice-icon" aria-hidden="true">
                <Icon icon={faClipboardList} />
              </span>
              <div className="order-notice-content">
                <strong>Đơn hàng mới</strong>
                <span>
                  {orderNotice.orderId
                    ? `Đơn #${orderNotice.orderId.slice(0, 8).toUpperCase()} đang chờ xử lý.`
                    : "Có đơn hàng mới đang chờ xử lý."}
                </span>
              </div>
              <button
                className="small primary order-notice-open"
                onClick={() => {
                  setOrderNotice(null);
                  navigateTo("orders");
                }}
              >
                Xem đơn
              </button>
              <button
                className="ghost message-notice-close"
                aria-label="Đóng thông báo đơn hàng"
                onClick={() => setOrderNotice(null)}
              >
                ✕
              </button>
            </div>
          )}
          {messageNotice && (
            <div
              key={messageNotice.id}
              className="message-notice"
              role="status"
              aria-live="polite"
            >
              <span className="message-notice-icon" aria-hidden="true">
                <Icon icon={faCommentDots} />
              </span>
              <button
                className="message-notice-content"
                onClick={() => {
                  if (messageNotice.conversationId)
                    sessionStorage.setItem(
                      "ro-chat-target-" + session.user.id,
                      messageNotice.conversationId,
                    );
                  setMessageNotice(null);
                  navigateTo("chat");
                  if (messageNotice.conversationId)
                    window.dispatchEvent(
                      new CustomEvent("ro:open-chat-conversation", {
                        detail: messageNotice.conversationId,
                      }),
                    );
                }}
              >
                <strong>{messageNotice.title}</strong>
                <span>{messageNotice.preview}</span>
                <small>Nhấn để mở hội thoại</small>
              </button>
              <button
                className="ghost message-notice-close"
                aria-label="Đóng thông báo tin nhắn"
                onClick={() => setMessageNotice(null)}
              >
                ✕
              </button>
            </div>
          )}
          {actionToast}
        </div>
      )}
    </AppContext.Provider>
  );
}

function Auth({ onLogin }: { onLogin: (s: Session) => void }) {
  const [mode, setMode] = useState("login"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [challenge, setChallenge] = useState<Row | null>(null),
    [ticket, setTicket] = useState(""),
    [identifier, setIdentifier] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [code, setCode] = useState(""),
    [fallbackReady, setFallbackReady] = useState(false),
    [fallbackFailed, setFallbackFailed] = useState(false);
  const changeMode = (m: string) => {
    setMode(m);
    setError("");
    setChallenge(null);
    setTicket("");
    setPassword("");
    setFallbackReady(false);
    setFallbackFailed(false);
  };
  useEffect(() => {
    if (mode !== "register" || !challenge || ticket || challenge.channel !== "zalo")
      return;
    if (challenge.fallbackAvailable) {
      setFallbackReady(true);
      return;
    }
    const seconds = Number(challenge.fallbackAfterSeconds ?? 0);
    if (!seconds) return;
    const timer = window.setTimeout(
      () => setFallbackReady(true),
      seconds * 1000,
    );
    return () => window.clearTimeout(timer);
  }, [challenge, mode, ticket]);
  const requestSmsFallback = async () => {
    if (!challenge) return;
    setBusy(true);
    setError("");
    setFallbackReady(false);
    try {
      const next = await api("/auth/registration/sms-fallback", "POST", {
        challengeId: challenge.challengeId,
      });
      setChallenge(next);
      setCode("");
      setFallbackFailed(false);
    } catch (e) {
      setFallbackFailed(true);
      setError(
        e instanceof Error ? e.message : "Không gửi được mã qua SMS",
      );
    } finally {
      setBusy(false);
    }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        onLogin(await api("/auth/login", "POST", { identifier, password }));
        return;
      }
      const kind = mode === "register" ? "registration" : "password-reset";
      if (!challenge) {
        setChallenge(
          await api("/auth/" + kind + "/otp", "POST", { phone: identifier }),
        );
        return;
      }
      if (!ticket) {
        const v = await api("/auth/" + kind + "/verify", "POST", {
          challengeId: challenge.challengeId,
          code,
        });
        setTicket(v.ticket);
        return;
      }
      if (mode === "register")
        await api("/auth/register", "POST", {
          ticket,
          displayName: name,
          password,
        });
      else
        await api("/auth/password-reset/confirm", "POST", { ticket, password });
      changeMode("login");
      setError(
        mode === "register"
          ? "Đăng ký thành công. Hãy đăng nhập."
          : "Đã đổi mật khẩu. Hãy đăng nhập.",
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Không kết nối được tới máy chủ",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auth-page">
      <section className="auth-intro">
        <div className="brand">
          <span className="brand-mark">
            <Icon icon={faBasketShopping} />
          </span>
          RealtimeOrders
        </div>
        <h1>
          Bữa ăn mỗi ngày,
          <br />
          mua sắm nhẹ nhàng.
        </h1>
        <p>
          Chọn thực phẩm, đặt hàng và theo dõi giao nhận.
          Mọi thông tin bạn cần, trong cùng một cửa hàng.
        </p>
        <img className="auth-grocery-art" src="/grocery-basket.svg" alt="" />
        <div className="auth-workflow" aria-label="Cách mua hàng">
          <div><span>01</span><strong>Chọn món hôm nay</strong><small>Sản phẩm, giá và lượng còn rõ ràng</small></div>
          <div><span>02</span><strong>Đặt hàng thuận tiện</strong><small>Chọn nơi nhận, kiểm tra phí giao</small></div>
          <div><span>03</span><strong>Theo dõi trực tiếp</strong><small>Cập nhật khi người bán xử lý đơn</small></div>
        </div>
        <div className="muted">Bài tập lớn Lập trình mạng · Nhóm 15</div>
      </section>
      <section className="auth-form">
        <div className="auth-inner">
          <div className="eyebrow">Chào mừng bạn</div>
          <h2>
            {mode === "login"
              ? "Đăng nhập"
              : mode === "register"
                ? "Tạo tài khoản"
                : "Khôi phục mật khẩu"}
          </h2>
          <p className="muted">
            {mode === "login"
              ? "Tiếp tục với số điện thoại hoặc email đã xác minh."
              : "Xác minh số điện thoại để bảo vệ tài khoản của bạn."}
          </p>
          {error && (
            <div role="alert" className="notice warn" style={{ marginTop: 18 }}>
              {error}
            </div>
          )}
          <form className="form" onSubmit={submit}>
            {!challenge && (
              <Field
                label={
                  mode === "login"
                    ? "Số điện thoại hoặc email"
                    : "Số điện thoại"
                }
              >
                <input
                  autoComplete="username"
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="0912 345 678"
                />
              </Field>
            )}
            {challenge && !ticket && (
              <>
                <p>
                  {challenge.channel === "zalo"
                    ? challenge.deliveryStatus === "accepted"
                      ? "Đã yêu cầu Zalo gửi mã tới " + identifier + "."
                      : "Zalo chưa gửi được mã tới " + identifier + "."
                    : challenge.channel === "sms"
                      ? "Mã xác minh đã được gửi qua SMS tới " + identifier + "."
                      : challenge.channel === "email"
                        ? "Mã xác minh đã được gửi tới " + identifier + "."
                        : "Mã xác minh demo dành cho " + identifier + "."}
                </p>
                {challenge.demo && challenge.demoCode && (
                  <div className="notice warn">
                    OTP demo:{" "}
                    <strong data-testid="demo-code">
                      {challenge.demoCode}
                    </strong>{" "}
                    · Chưa gửi Zalo/SMS thật
                  </div>
                )}
                {challenge.channel !== "zalo" ||
                challenge.deliveryStatus === "accepted" ? (
                  <Field label="Mã xác minh 6 số">
                    <input
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      required
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                    />
                  </Field>
                ) : null}
                {mode === "register" && challenge.channel === "zalo" && (
                  <>
                    {fallbackFailed ? (
                      <p className="muted">
                        Không gửi được SMS. Hãy thử lại sau giới hạn hiện hành.
                      </p>
                    ) : (
                      <button
                        type="button"
                        className="ghost"
                        disabled={busy || !fallbackReady}
                        onClick={requestSmsFallback}
                      >
                        {fallbackReady
                          ? "Gửi mã qua SMS"
                          : "Có thể chọn SMS sau 60 giây"}
                      </button>
                    )}
                  </>
                )}
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    setChallenge(null);
                    setCode("");
                    setFallbackReady(false);
                    setFallbackFailed(false);
                  }}
                >
                  Đổi số hoặc yêu cầu mã mới
                </button>
              </>
            )}
            {(mode === "login" || ticket) && (
              <>
                {mode === "register" && (
                  <Field label="Họ tên">
                    <input
                      required
                      maxLength={100}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </Field>
                )}
                <Field
                  label={
                    mode === "login"
                      ? "Mật khẩu"
                      : "Mật khẩu mới (ít nhất 10 ký tự)"
                  }
                >
                  <input
                    type="password"
                    autoComplete={
                      mode === "login" ? "current-password" : "new-password"
                    }
                    required
                    minLength={mode === "login" ? 1 : 10}
                    maxLength={128}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </Field>
              </>
            )}
            <button
              className="primary"
              disabled={
                busy ||
                (mode === "register" &&
                  !!challenge &&
                  !ticket &&
                  challenge.channel === "zalo" &&
                  challenge.deliveryStatus !== "accepted")
              }
            >
              {busy
                ? "Đang xử lý…"
                : mode === "login"
                  ? "Đăng nhập"
                  : !challenge
                    ? "Nhận mã xác minh"
                    : !ticket
                      ? challenge?.deliveryStatus === "unavailable"
                        ? "Chưa gửi được mã"
                        : "Xác minh mã"
                      : mode === "register"
                        ? "Tạo tài khoản"
                        : "Đổi mật khẩu"}
            </button>
          </form>
          <div className="auth-links">
            <button
              className="ghost"
              onClick={() =>
                changeMode(mode === "login" ? "register" : "login")
              }
            >
              {mode === "login" ? "Tạo tài khoản" : "Quay lại đăng nhập"}
            </button>
            {mode === "login" && (
              <button className="ghost" onClick={() => changeMode("reset")}>
                Quên mật khẩu?
              </button>
            )}
          </div>
          <p className="demo-label">
            Tài khoản demo được tạo riêng khi cài đặt. Thông tin đăng nhập nằm
            trong tệp runtime/demo-accounts.local.json của dự án.
          </p>
        </div>
      </section>
    </div>
  );
}

function useData(path: string) {
  const previousPath = useRef(path);
  const [catalogRevision, setCatalogRevision] = useState(0);
  useEffect(() => {
    if (!path.startsWith("/catalog/upcoming")) return;
    const update = () => setCatalogRevision(value => value + 1);
    window.addEventListener("ro:catalog", update);
    return () => window.removeEventListener("ro:catalog", update);
  }, [path]);
  const { refresh, notify, session } = useApp();
  const [data, setData] = useState<any>(
      path === "/catalog/offers" && catalogOwner === session.user.id
        ? catalogModel
        : null,
    ),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    if (path === "/catalog/offers") {
      if (catalogOwner === session.user.id) {
        setData(catalogModel);
        setLoading(!catalogModel);
      }
      return;
    }
    let live = true;
    if (previousPath.current !== path) {
      setData(null);
      previousPath.current = path;
    }
    setLoading(true);
    api(path)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) notify(e.message, true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [path, refresh, notify, catalogRevision]);
  useEffect(() => {
    if (path !== "/catalog/offers") return;
    const update = () => {
      if (catalogOwner === session.user.id) {
        setData(catalogModel);
        setLoading(!catalogModel);
      }
    };
    window.addEventListener("ro:catalog", update);
    return () => window.removeEventListener("ro:catalog", update);
  }, [path]);
  return { data, loading, setData };
}
function Heading({
  title,
  sub,
  children,
  className,
}: {
  title: string;
  sub: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const { session } = useApp();
  const area = session?.user.role === "ADMIN" ? "Quản trị" : session?.user.role === "SELLER" ? "Người bán" : session?.user.role === "SHIPPER" ? "Giao nhận" : "Cửa hàng";
  return (
    <div className={className ? "page-heading " + className : "page-heading"}>
      <div>
        <nav className="breadcrumbs" aria-label="Đường dẫn">
          <span>RealtimeOrders</span><span aria-hidden="true">/</span><strong>{area}</strong>
        </nav>
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      {children}
    </div>
  );
}

function Profile() {
  const { session, mutate, notify, online, setSession } = useApp(),
    { data: addresses } = useData("/me/addresses");
  const [editing, setEditing] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [name, setName] = useState(session.user.display_name),
    [email, setEmail] = useState(""),
    [challenge, setChallenge] = useState<Row | null>(null),
    [code, setCode] = useState("");
  const saveAddress = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await mutate(
        "/me/addresses" + (editing?.id ? "/" + editing.id : ""),
        { ...editing, note: editing?.note ?? "", expectedVersion: String(editing?.version ?? "") },
        editing?.id ? "PATCH" : "POST",
      );
      setEditing(null);
      notify("Đã lưu địa chỉ");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Heading
        title="Hồ sơ & địa chỉ"
        sub="Lưu tối đa 3 địa chỉ. Đơn đã gửi giữ nguyên thông tin tại thời điểm đặt."
      />
      <div className="split">
        <section className="panel">
          <div className="panel-head">
            <h2>Địa chỉ nhận hàng</h2>
            <button
              disabled={!online || addresses?.length >= 3}
              onClick={() =>
                setEditing({
                  recipientName: session.user.display_name,
                  phone: session.user.phone_e164,
                  addressLine: "",
                  note: "",
                })
              }
            >
              <Icon icon={faPlus} /> Thêm
            </button>
          </div>
          {addresses?.map((a: Row) => (
            <div className="list-row" key={a.id}>
              <div className="row-heading">
                <strong>
                  {a.recipient_name} · {a.phone_e164}
                </strong>
                {a.id === session.user.default_address_id && (
                  <span className="status ACTIVE">Mặc định</span>
                )}
              </div>
              <p>{a.address_line}</p>
              <p className="muted">{a.note}</p>
              <div className="actions" style={{ marginTop: 10 }}>
                <button
                  className="small"
                  disabled={!online}
                  onClick={() =>
                    setEditing({
                      ...a,
                      recipientName: a.recipient_name,
                      phone: a.phone_e164,
                      addressLine: a.address_line,
                      note: a.note ?? "",
                    })
                  }
                >
                  Sửa
                </button>
                <button
                  className="small"
                  disabled={!online}
                  onClick={async () => {
                    try {
                      await mutate(
                        "/me/addresses/" + a.id,
                        {
                          makeDefault: true,
                          expectedVersion: String(a.version),
                        },
                        "PATCH",
                      );
                      const s = await api("/auth/session");
                      setSession(s);
                    } catch {}
                  }}
                >
                  Chọn mặc định
                </button>
                <button
                  className="small danger"
                  disabled={!online}
                  onClick={async () => {
                    if (!confirm("Xóa địa chỉ này?")) return;
                    try {
                      await mutate(
                        "/me/addresses/" + a.id,
                        { expectedVersion: String(a.version) },
                        "DELETE",
                      );
                      setSession(await api("/auth/session"));
                    } catch {}
                  }}
                >
                  Xóa
                </button>
              </div>
            </div>
          ))}
          {addresses?.length === 0 && (
            <Empty title="Chưa có địa chỉ">
              Thêm một địa chỉ để bắt đầu đặt hàng.
            </Empty>
          )}
        </section>
        <section className="summary">
          <h2>Thông tin tài khoản</h2>
          <form
            className="form"
            style={{ marginTop: 18 }}
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await mutate(
                  "/me",
                  {
                    displayName: name,
                    expectedVersion: String(session.user.version),
                  },
                  "PATCH",
                );
                setSession(await api("/auth/session"));
                notify("Đã cập nhật tên");
              } catch {}
            }}
          >
            <Field label="Họ tên">
              <input
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Số điện thoại đã xác minh">
              <input value={session.user.phone_e164} disabled />
            </Field>
            <button disabled={!online}>Lưu tên hiển thị</button>
          </form>
          <hr />
          <h3>Email tùy chọn</h3>
          {session.user.email_normalized && (
            <p>{session.user.email_normalized}</p>
          )}
          <form
            className="form"
            style={{ marginTop: 14 }}
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                if (!challenge)
                  setChallenge(
                    await api("/auth/email/challenge", "POST", { email }),
                  );
                else {
                  await api("/auth/email/verify", "POST", {
                    challengeId: challenge.challengeId,
                    code,
                  });
                  setChallenge(null);
                  setSession(await api("/auth/session"));
                  notify("Email đã được xác minh");
                }
              } catch (e) {
                notify((e as Error).message, true);
              }
            }}
          >
            {!challenge ? (
              <Field label="Email để đăng nhập">
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
            ) : (
              <>
                <Field label="Mã xác minh email">
                  <input
                    required
                    pattern="[0-9]{6}"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </Field>
                {challenge.demo && (
                  <div className="notice warn">
                    Mã email demo: {challenge.demoCode}
                  </div>
                )}
              </>
            )}
            <button disabled={!online}>
              {challenge ? "Xác minh email" : "Gửi mã xác minh"}
            </button>
          </form>
        </section>
      </div>
      {editing && (
        <Modal
          title={editing.id ? "Sửa địa chỉ" : "Thêm địa chỉ"}
          close={() => setEditing(null)}
        >
          <form className="form form-grid" onSubmit={saveAddress}>
            <Field label="Người nhận">
              <input
                required
                value={editing.recipientName}
                onChange={(e) =>
                  setEditing({ ...editing, recipientName: e.target.value })
                }
              />
            </Field>
            <Field label="Số điện thoại">
              <input
                required
                value={editing.phone}
                onChange={(e) =>
                  setEditing({ ...editing, phone: e.target.value })
                }
              />
            </Field>
            <div className="wide">
              <LocationPicker
                initial={editing.addressLine}
                initialPoint={editing.latitude != null && editing.longitude != null ? { latitude: Number(editing.latitude), longitude: Number(editing.longitude) } : null}
                onSelect={(loc) =>
                  setEditing((prev: Row | null) =>
                    prev
                      ? {
                          ...prev,
                          locationToken: loc.locationToken,

                        }
                      : prev,
                  )
                }
              />

            </div>
            <Field label="Địa chỉ cụ thể" wide>
              <textarea
                required
                minLength={5}
                maxLength={500}
                value={editing.addressLine}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    addressLine: e.target.value,
                  })
                }
              />
            </Field>
            <Field label="Ghi chú" wide>
              <input
                maxLength={500}
                value={editing.note ?? ""}
                onChange={(e) =>
                  setEditing({ ...editing, note: e.target.value })
                }
              />
            </Field>
            <button className="primary" disabled={busy || !online}>
              Lưu địa chỉ
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

async function uploadImage(file: File, purpose = "CHAT") {
  if (file.size > 5 * 1024 * 1024) throw new Error("Ảnh tối đa 5 MiB");
  const form = new FormData();
  form.append("purpose", purpose);
  form.append("file", file);
  const response = await fetch("/api/v1/media", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: form,
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error?.message ?? "Không tải được ảnh");
  return data;
}
function Chat({ admin }: { admin: boolean }) {
  const { session, online, refresh, mutate, notify } = useApp();
  const [conversations, setConversations] = useState<Row[]>([]),
    [selected, setSelected] = useState(""),
    [messages, setMessages] = useState<Row[]>([]),
    [content, setContent] = useState(""),
    [assets, setAssets] = useState<Row[]>([]),
    [busy, setBusy] = useState(false),
    [more, setMore] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let live = true;
    (admin
      ? api("/admin/conversations")
      : api("/conversations/me").then(() => api("/conversations"))
    )
      .then((c) => {
        if (live) {
          setConversations(c);
          const targetKey = "ro-chat-target-" + session.user.id;
          const requested = sessionStorage.getItem(targetKey);
          const requestedConversation = c.find(
            (conversation: Row) => conversation.id === requested,
          );
          const next = requestedConversation?.id ?? c[0]?.id ?? "";
          setSelected((old) => requestedConversation ? next : c.some((conversation: Row) => conversation.id === old) ? old : next);
          if (requestedConversation) sessionStorage.removeItem(targetKey);
        }
      })
      .catch((e) => notify(e.message, true));
    return () => {
      live = false;
    };
  }, [admin, refresh, notify, session.user.id]);
  useEffect(() => {
    const openConversation = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (!id || !conversations.some((conversation) => conversation.id === id)) return;
      sessionStorage.removeItem("ro-chat-target-" + session.user.id);
      setSelected(id);
      setMessages([]);
    };
    window.addEventListener("ro:open-chat-conversation", openConversation);
    return () =>
      window.removeEventListener("ro:open-chat-conversation", openConversation);
  }, [conversations, session.user.id]);
  useEffect(() => {
    if (!selected) return;
    let live = true;
    api("/conversations/" + selected + "/messages")
      .then((m) => {
        if (live) {
          setMessages(m);
          setMore(m.length === 50);
        }
      })
      .catch((e) => notify(e.message, true));
    return () => {
      live = false;
    };
  }, [selected, refresh, notify]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length]);
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    try {
      await mutate("/conversations/" + selected + "/messages", {
        clientMessageId: crypto.randomUUID(),
        text: content,
        assetIds: assets.map((a) => a.id),
      });
      setContent("");
      setAssets([]);
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Heading
        title={admin ? "Tin nhắn khách hàng" : "Nhắn người bán"}
        sub="Hội thoại riêng, lưu lịch sử và nhận cập nhật khi có kết nối."
      />
      <div className="panel chat-layout">
        <div className="chat-sidebar">
          {conversations.map((c) => (
            <button
              key={c.id}
              className={selected === c.id ? "primary" : "ghost"}
              onClick={() => {
                setSelected(c.id);
                setMessages([]);
                setContent("");
                setAssets([]);
              }}
            >
              {admin ? `${c.display_name}${session.user.role === "ADMIN" && c.shop_name ? " · " + c.shop_name : ""}` : c.shop_name}
            </button>
          ))}
          {!conversations.length && <p className="muted">Chưa có hội thoại</p>}
        </div>
        <div className="chat-area">
          <div className="chat-messages" role="log" aria-live="polite">
            {more && messages.length > 0 && (
              <button
                className="small"
                onClick={async () => {
                  try {
                    const older = await api(
                      "/conversations/" +
                        selected +
                        "/messages?before=" +
                        messages[0].id,
                    );
                    setMessages([...older, ...messages]);
                    setMore(older.length === 50);
                  } catch (e) {
                    notify((e as Error).message, true);
                  }
                }}
              >
                Tin nhắn cũ hơn
              </button>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                className={
                  "message " + (m.sender_id === session.user.id ? "own" : "")
                }
              >
                {m.text_sanitized}
                {m.attachments.map((a: Row) => (
                  <a
                    key={a.asset_id}
                    href={"/api/v1/media/" + a.asset_id}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <img
                      alt="Ảnh trong hội thoại"
                      src={"/api/v1/media/" + a.asset_id}
                    />
                  </a>
                ))}
                <small>
                  {m.sender_id === session.user.id ? "Bạn" : "Đối phương"} ·{" "}
                  {date(m.created_at)}
                </small>
              </div>
            ))}
            {!messages.length && (
              <Empty title="Bắt đầu trao đổi">
                Gửi nội dung hoặc ảnh để người bán hỗ trợ.
              </Empty>
            )}
            <div ref={bottom} />
          </div>
          <form className="chat-composer" onSubmit={send}>
            {assets.length > 0 && (
              <div className="attachment-preview">
                {assets.length} ảnh đã tải{" "}
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => setAssets([])}
                >
                  Bỏ ảnh
                </button>
              </div>
            )}
            <textarea
              aria-label="Nội dung tin nhắn"
              maxLength={4000}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Nhập tin nhắn…"
            />
            <label className="check-label" style={{ cursor: "pointer" }}>
              <Icon icon={faImage} />
              <span className="muted">Ảnh</span>
              <input
                aria-label="Chọn ảnh gửi chat"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                style={{ display: "none" }}
                disabled={!online || busy || assets.length >= 3}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setBusy(true);
                  try {
                    const a = await uploadImage(file);
                    setAssets((old) => [...old, a]);
                  } catch (e) {
                    notify((e as Error).message, true);
                  } finally {
                    setBusy(false);
                    e.target.value = "";
                  }
                }}
              />
            </label>
            <button
              className="primary"
              disabled={
                !online ||
                busy ||
                !selected ||
                (!content.trim() && !assets.length)
              }
            >
              Gửi
            </button>
          </form>
        </div>
      </div>
    </>
  );
}

function Notifications() {
  const { data } = useData("/notifications");
  const { mutate, online } = useApp();
  return (
    <>
      <Heading
        title="Thông báo"
        sub="Cập nhật hàng, đơn, yêu cầu và tin nhắn được lưu để bạn đọc lại."
      />
      <div className="panel">
        {data?.map((n: Row) => (
          <div className="list-row" key={n.id}>
            <div className="row-heading">
              <strong>{n.payload.message ?? "Cập nhật mới"}</strong>
              <span className="date">{date(n.created_at)}</span>
            </div>
            {n.payload.status && <Status value={n.payload.status} />}
            <div className="actions">
              {n.kind === "POST_INTERACTION" && <button type="button" className="small" onClick={() => window.dispatchEvent(new CustomEvent("ro:navigate", {detail: ["ADMIN","SELLER"].includes(activeRole) ? "offers" : "feed"}))}>{["ADMIN","SELLER"].includes(activeRole) ? "Xem lịch sử mở bán" : "Xem bảng tin"}</button>}
              {n.read_at ? (
                <small>Đã đọc</small>
              ) : (
                <button
                  className="small"
                  disabled={!online}
                  onClick={async () => {
                    try {
                      await mutate("/notifications/" + n.id + "/read", {});
                    } catch {}
                  }}
                >
                  Đánh dấu đã đọc
                </button>
              )}
            </div>
          </div>
        ))}
        {data?.length === 0 && <Empty title="Bạn đã xem hết cập nhật" />}
      </div>
    </>
  );
}

function QuickConfigCreate({ kind, close }: { kind: "groups" | "categories"; close: () => void }) {
  const { mutate, notify, online } = useApp();
  const [busy, setBusy] = useState(false);
  const isGroup = kind === "groups";
  return <section className="panel inline-create" aria-label={isGroup ? "Thêm nhóm khách hàng" : "Thêm danh mục"}>
    <div className="row-heading"><h2>{isGroup ? "Thêm nhóm khách hàng" : "Thêm danh mục"}</h2><button type="button" disabled={busy} onClick={close}>Đóng</button></div>
    <form className="form form-grid" onSubmit={async event => {
      event.preventDefault(); if (busy || !online) return;
      const data = new FormData(event.currentTarget);
      setBusy(true);
      try {
        await mutate("/admin/config/" + kind, {name: String(data.get("name") ?? "").trim(), ...(isGroup ? {code: String(data.get("code") ?? "").trim()} : {}), active: true});
        notify(isGroup ? "Đã thêm nhóm khách hàng" : "Đã thêm danh mục"); close();
      } catch {} finally { setBusy(false); }
    }}>
      {isGroup && <Field label="Mã nhóm"><input name="code" required maxLength={50} /></Field>}
      <Field label={isGroup ? "Tên nhóm" : "Tên danh mục"}><input name="name" required maxLength={150} /></Field>
      <div className="actions"><button className="primary" disabled={busy || !online}>Lưu {isGroup ? "nhóm" : "danh mục"}</button></div>
    </form>
  </section>;
}

function Products() {
  const { session, mutate, notify, online } = useApp();
  const adminView = session.user.role === "ADMIN";
  const { data } = useData("/admin/products"),
    { data: categories } = useData("/admin/config/categories"),
    { data: units } = useData("/admin/config/units"),
    { data: groups } = useData("/admin/config/groups");
  const [form, setForm] = useState<Row | null>(null),
    [bulk, setBulk] = useState<Row[] | null>(null),
    [busy, setBusy] = useState(false),
    [imageUrlDraft, setImageUrlDraft] = useState(""),
    [catalogSearch, setCatalogSearch] = useState(""),
    [catalogCategory, setCatalogCategory] = useState("all"),
    [addingCategory, setAddingCategory] = useState(false);
  const edit = (p?: Row) => {
    setImageUrlDraft("");
    setForm(
      p
        ? {
            ...p,
            description: p.description ?? "",
            categoryId: p.category_id,
            unitId: p.unit_id,
            quantityStep: p.quantity_step,
            listPrice: p.list_price ?? "",
            allowedGroupIds: p.allowed_group_ids,
            active:
              p.active === true || p.active === 1 || p.active === "1",
            imageEntries: (p.images ?? []).flatMap((image: Row) =>
              image.asset_id
                ? [{ kind: "asset", assetId: image.asset_id }]
                : image.source_url
                  ? [{ kind: "url", url: image.source_url }]
                  : [],
            ),
          }
        : {
            name: "",
            description: "",
            categoryId: categories?.[0]?.id,
            unitId: units?.[0]?.id,
            quantityStep: "1",
            listPrice: "",
            allowedGroupIds: null,
            active: true,
            imageEntries: [],
          },
    );
  };
  const preparedImages = (): Row[] | null => {
    if (!form) return null;
    const value = imageUrlDraft.trim();
    if (!value) return form.imageEntries;
    let parsed: URL;
    try { parsed = new URL(value); }
    catch { notify("URL ảnh chưa hợp lệ", true); return null; }
    if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password) {
      notify("URL ảnh phải là liên kết HTTPS công khai", true);
      return null;
    }
    const url = parsed.href;
    if (form.imageEntries.some((image: Row) => image.kind === "url" && image.url === url)) {
      return form.imageEntries;
    }
    if (form.imageEntries.length >= 5) {
      notify("Mỗi sản phẩm có thể có tối đa 5 ảnh", true);
      return null;
    }
    return [...form.imageEntries, { kind: "url", url }];
  };
  const addImageUrl = () => {
    if (!form || !imageUrlDraft.trim()) return;
    const imageEntries = preparedImages();
    if (!imageEntries) return;
    setForm({ ...form, imageEntries });
    notify(imageEntries.length === form.imageEntries.length
      ? "Ảnh đã có trong danh sách. Bấm Lưu sản phẩm để lưu."
      : "Đã thêm ảnh vào danh sách. Bấm Lưu sản phẩm để lưu.");
  };
  const filteredProducts = (data ?? []).filter((p: Row) => {
    const matchesCategory =
      catalogCategory === "all" || p.category_id === catalogCategory;
    const matchesSearch =
      !catalogSearch ||
      [p.name, p.sku]
        .join(" ")
        .toLocaleLowerCase("vi-VN")
        .includes(catalogSearch.toLocaleLowerCase("vi-VN"));
    return matchesCategory && matchesSearch;
  });
  return (
    <>
      <Heading
        title="Danh mục sản phẩm"
        sub="Quản lý SKU, đơn vị, bước số lượng và ảnh. Lịch sử đơn giữ nguyên dữ liệu cũ."
      >
        {adminView && <button disabled={!online} onClick={() => setAddingCategory(value => !value)}>Thêm danh mục</button>}
        <button className="primary" disabled={!online} onClick={() => { setBulk(null); edit(); }}>
          <Icon icon={faPlus} /> Thêm sản phẩm
        </button>
      </Heading>
      {addingCategory && <QuickConfigCreate kind="categories" close={() => setAddingCategory(false)} />}
      {bulk && <section className="panel inline-create" aria-label="Thêm nhanh sản phẩm">
        <div className="row-heading"><h2>Thêm nhanh sản phẩm</h2><div className="actions"><button type="button" disabled={busy} onClick={() => {setBulk(null); edit();}}>Thêm một sản phẩm</button><button type="button" disabled={busy} onClick={() => setBulk(null)}>Đóng</button></div></div>
        <form className="form" onSubmit={async e => {
          e.preventDefault();
          if (busy || !online) return;
          setBusy(true);
          try {
            const saved = await mutate("/admin/products/bulk", {items:bulk});
            setBulk(null);
            notify(`Đã thêm ${saved.length} sản phẩm`);
          } catch {} finally { setBusy(false); }
        }}>
          <Field label="Số sản phẩm cần thêm">
            <input type="number" min="1" max="20" step="1" value={bulk.length}
              disabled={busy} onChange={e => {
                const count = Number(e.target.value);
                if (!Number.isInteger(count) || count < 1 || count > 20) return;
                setBulk(current => {
                  if (!current) return current;
                  const next = current.slice(0, count);
                  while (next.length < count) next.push({name:"",categoryId:categories[0].id,unitId:units[0].id,quantityStep:"1",listPrice:""});
                  return next;
                });
              }} />
          </Field>
          <p className="muted">Mỗi mặt hàng được cấp SKU tự động. Có thể bổ sung mô tả, ảnh và nhóm khách sau khi lưu.</p>
          {bulk.map((item, index) => <fieldset className="food-receipt-line" key={index} disabled={busy}>
            <legend>Sản phẩm {index + 1}</legend>
            <label>Tên sản phẩm<input required maxLength={150} value={item.name} onChange={e => {
              const value=e.target.value;
              setBulk(current => current?.map((row,i) => i===index ? {...row,name:value} : row) ?? null);
            }} /></label>
            <label>Danh mục<select required value={item.categoryId} onChange={e => {
              const value=e.target.value;
              setBulk(current => current?.map((row,i) => i===index ? {...row,categoryId:value} : row) ?? null);
            }}>{categories?.map((category: Row) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            <label>Đơn vị<select required value={item.unitId} onChange={e => {
              const value=e.target.value;
              setBulk(current => current?.map((row,i) => i===index ? {...row,unitId:value} : row) ?? null);
            }}>{units?.map((unit: Row) => <option key={unit.id} value={unit.id}>{unit.label}</option>)}</select></label>
            <label>Bước số lượng<input type="number" min="0.001" step="0.001" required value={item.quantityStep} onChange={e => {
              const value=e.target.value;
              setBulk(current => current?.map((row,i) => i===index ? {...row,quantityStep:value} : row) ?? null);
            }} /></label>
            <label>Giá niêm yết (đ)<input type="number" min="0" step="1" value={item.listPrice} onChange={e => {
              const value=e.target.value;
              setBulk(current => current?.map((row,i) => i===index ? {...row,listPrice:value} : row) ?? null);
            }} /></label>
          </fieldset>)}
          <button className="primary" disabled={!online || busy}>Lưu {bulk.length} sản phẩm</button>
        </form>
      </section>}
      {form && (
        <section className="panel inline-create" aria-label={form.id ? "Sửa sản phẩm" : "Thêm sản phẩm"}>
          <div className="row-heading"><h2>{form.id ? "Sửa sản phẩm" : "Thêm sản phẩm"}</h2><button type="button" disabled={busy} onClick={() => setForm(null)}>Đóng</button></div>
          {!form.id && <button type="button" disabled={busy || !categories?.length || !units?.length} onClick={() => {setForm(null); setBulk([{name:"",categoryId:categories[0].id,unitId:units[0].id,quantityStep:"1",listPrice:""}]);}}>Thêm nhanh nhiều sản phẩm</button>}
          <form
            className="form form-grid"
            onSubmit={async (e) => {
              e.preventDefault();
              const imageEntries = preparedImages();
              if (!imageEntries) return;
              setBusy(true);
              try {
                const { imageEntries: previousImages, ...productForm } = form;
                const saved = await mutate(
                  "/admin/products" + (form.id ? "/" + form.id : ""),
                  {
                    ...productForm,
                    description: productForm.description ?? "",
                    images: imageEntries.map((image: Row) =>
                      image.kind === "asset"
                        ? { assetId: image.assetId }
                        : { url: image.url },
                    ),
                    expectedVersion: String(form.version ?? ""),
                  },
                  form.id ? "PATCH" : "POST",
                );
                setForm(null);
                notify(
                  form.id ? "Đã lưu sản phẩm" : `Đã thêm sản phẩm · ${saved.sku}`,
                );
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Giá niêm yết (đ)">
              <input type="number" min="0" step="1" value={form.listPrice}
                onChange={e => setForm({ ...form, listPrice: e.target.value })} />
            </Field>
            <AudienceFields
              groups={groups ?? []}
              value={form.allowedGroupIds ?? null}
              onChange={(v) => setForm({ ...form, allowedGroupIds: v })}
              legend="Nhóm được phép mua sản phẩm"
            />
            <p className="muted">
              Khách chỉ thấy sản phẩm nếu được phép ở cả sản phẩm và menu ngày.
            </p>
            <Field label="Tên sản phẩm" wide>
              <input
                required
                maxLength={150}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Mã SKU tự động">
              <input
                readOnly
                value={form.id ? form.sku : "Tự cấp khi lưu sản phẩm"}
              />
            </Field>
            <Field label="Danh mục">
              <select
                required
                value={form.categoryId ?? ""}
                onChange={(e) =>
                  setForm({ ...form, categoryId: e.target.value })
                }
              >
                {categories?.map((c: Row) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Đơn vị">
              <select
                required
                value={form.unitId ?? ""}
                onChange={(e) => setForm({ ...form, unitId: e.target.value })}
              >
                {units?.map((u: Row) => (
                  <option key={u.id} value={u.id}>
                    {u.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Bước số lượng">
              <input
                required
                type="number"
                min=".001"
                step=".001"
                value={form.quantityStep}
                onChange={(e) =>
                  setForm({ ...form, quantityStep: e.target.value })
                }
              />
            </Field>
            <Field label="Mô tả" wide>
              <textarea
                maxLength={2000}
                value={form.description ?? ""}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
            </Field>
            <label className="check-label">
              <input
                type="checkbox"
                checked={form.active}
                onChange={(e) => setForm({ ...form, active: e.target.checked })}
              />
              Đang sử dụng
            </label>
            <Field label="Ảnh sản phẩm (tối đa 5)">
              <input
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp"
                disabled={busy || form.imageEntries.length >= 5}
                onChange={async (e) => {
                  const input = e.currentTarget;
                  const files = Array.from(input.files ?? []);
                  input.value = "";
                  if (!files.length) return;
                  const availableSlots = Math.max(0, 5 - form.imageEntries.length);
                  if (files.length > availableSlots)
                    notify("Mỗi sản phẩm có thể có tối đa 5 ảnh", true);
                  const selectedFiles = files.slice(0, availableSlots);
                  if (!selectedFiles.length) return;
                  setBusy(true);
                  const uploadedIds: string[] = [];
                  try {
                    for (const file of selectedFiles) {
                      const img = await uploadImage(file, "PRODUCT");
                      uploadedIds.push(img.id);
                    }
                    setForm({
                      ...form,
                      imageEntries: [
                        ...form.imageEntries,
                        ...uploadedIds.map((assetId) => ({ kind: "asset", assetId })),
                      ],
                    });
                  } catch (e) {
                    if (uploadedIds.length)
                      setForm({
                        ...form,
                        imageEntries: [
                          ...form.imageEntries,
                          ...uploadedIds.map((assetId) => ({ kind: "asset", assetId })),
                        ],
                      });
                    notify((e as Error).message, true);
                  } finally {
                    setBusy(false);
                  }
                }}
              />
            </Field>
            <Field label="Dán URL ảnh HTTPS" wide>
              <div className="product-image-url-row">
                <input
                  type="url"
                  maxLength={2048}
                  value={imageUrlDraft}
                  disabled={busy || form.imageEntries.length >= 5}
                  placeholder="https://example.com/anh-san-pham.jpg"
                  onChange={(e) => setImageUrlDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addImageUrl();
                    }
                  }}
                />
                <button
                  type="button"
                  disabled={busy || !online || form.imageEntries.length >= 5 || !imageUrlDraft.trim()}
                  onClick={addImageUrl}
                >
                  Thêm URL
                </button>
              </div>
            </Field>
            <p className="field-hint wide">
              Ảnh tải lên nhận JPEG, PNG hoặc WebP tối đa 5 MiB. URL cần trỏ
              trực tiếp tới ảnh HTTPS công khai; khách sẽ tải ảnh từ máy chủ đó.
              Ảnh đầu tiên được dùng làm ảnh đại diện. Bấm Thêm URL để xem trước, rồi Lưu sản phẩm để lưu vào hệ thống. Muốn thay ảnh cũ, bấm Gỡ rồi thêm ảnh mới.
            </p>
            <div className="product-image-editor wide">
              <div className="product-image-editor-heading">
                <strong>{form.imageEntries.length}/5 ảnh</strong>
                {busy && <span>Đang tải ảnh…</span>}
              </div>
              {form.imageEntries.length ? (
                <div className="product-image-editor-grid">
                  {form.imageEntries.map((image: Row, index: number) => {
                    const source =
                      image.kind === "url"
                        ? image.url
                        : productImageSrc(image.assetId);
                    return (
                    <div className="product-image-editor-card" key={index}>
                      <img
                        src={source}
                        alt={`Ảnh sản phẩm ${index + 1}`}
                        loading="lazy"
                      />
                      <div className="product-image-editor-card-footer">
                        <span>{index === 0 ? "Ảnh đại diện" : `Ảnh ${index + 1}`}{image.kind === "url" ? " · URL" : " · Tải lên"}</span>
                        <button
                          type="button"
                          className="small ghost"
                          disabled={busy}
                          onClick={() => {
                            setForm({
                              ...form,
                              imageEntries: form.imageEntries.filter(
                                (_: Row, i: number) => i !== index,
                              ),
                            });
                          }}
                        >
                          Gỡ
                        </button>
                      </div>
                    </div>
                    );
                  })}
                </div>
              ) : (
                <div className="product-image-editor-empty">
                  <Icon icon={faImage} aria-hidden="true" />
                  <span>Chưa có ảnh. Thêm ảnh để khách dễ nhận biết sản phẩm.</span>
                </div>
              )}
            </div>
            <button className="primary" disabled={!online || busy}>
              Lưu sản phẩm
            </button>
            {form.id && (
              <button
                type="button"
                className="danger"
                disabled={!online || busy}
                onClick={async () => {
                  if (!confirm("Ngừng sử dụng và xóa mềm sản phẩm này?"))
                    return;
                  try {
                    await mutate(
                      "/admin/products/" + form.id,
                      { expectedVersion: String(form.version) },
                      "DELETE",
                    );
                    setForm(null);
                  } catch {}
                }}
              >
                Xóa mềm sản phẩm
              </button>
            )}
          </form>
        </section>
      )}
      <section className="panel">
        <div className="form-grid">
          <Field label="Lọc theo danh mục">
            <select
              value={catalogCategory}
              onChange={(e) => setCatalogCategory(e.target.value)}
            >
              <option value="all">Tất cả danh mục</option>
              {categories
                ?.filter((category: Row) => category.active)
                .map((category: Row) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Tìm theo tên hoặc SKU">
            <input
              type="search"
              value={catalogSearch}
              onChange={(e) => setCatalogSearch(e.target.value)}
              placeholder="Nhập tên sản phẩm hoặc mã SKU"
            />
          </Field>
        </div>
        <p className="muted" style={{ margin: "12px 0" }}>
          Hiển thị {filteredProducts.length} / {data?.length ?? 0} sản phẩm
        </p>
        <div className="table-scroll">
          <table>
            <thead>
            <tr>
              <th>Ảnh</th>
              <th>SKU</th>
              <th>Tên sản phẩm</th>
              <th>Nhóm được phép mua</th>
              <th>Đơn vị / bước</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filteredProducts.map((p: Row) => (
              <tr key={p.id}>
                <td className="product-list-image-cell">
                  {p.images?.[0] ? (
                    <img
                      className="product-list-image"
                      src={productImageSrc(p.images[0])}
                      alt={"Ảnh đại diện " + p.name}
                      loading="lazy"
                    />
                  ) : (
                    <span className="product-list-no-image">Chưa có ảnh</span>
                  )}
                  {p.images?.length > 1 && (
                    <span className="product-image-count">
                      {p.images.length} ảnh
                    </span>
                  )}
                </td>
                <td className="muted">{p.sku}</td>
                <td>
                  <strong>{p.name}</strong>
                  <div className="product-subtitle">{p.description}</div>
                  <div className="muted">
                    Giá nhập:{" "}
                    {p.list_price == null ? "Chưa có giá niêm yết" : "Niêm yết " + money(p.list_price)}
                  </div>
                </td>
                <td>
                  {p.allowed_group_ids == null
                    ? "Tất cả nhóm"
                    : Array.isArray(p.allowed_group_ids)
                      ? p.allowed_group_ids
                          .map(
                            (id: string) =>
                              groups?.find((group: Row) => group.id === id)
                                ?.name ?? "Nhóm đã ngừng dùng",
                          )
                          .join(", ") || "Chưa chọn nhóm"
                      : "Chưa cấu hình"}
                </td>
                <td>
                  {units?.find((u: Row) => u.id === p.unit_id)?.label} ·{" "}
                  {qty(p.quantity_step)}
                </td>
                <td><span className={"status " + (p.active ? "ACTIVE" : "INACTIVE")}>{p.active ? "Đang dùng" : "Ngừng dùng"}</span></td>
                <td>
                  <button className="small" onClick={() => edit(p)}>
                    Sửa
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && filteredProducts.length === 0 && (
          <Empty title="Không có sản phẩm phù hợp">
            Thử chọn danh mục khác hoặc xóa bớt từ khóa tìm kiếm.
          </Empty>
        )}
        </div>
      </section>

    </>
  );
}

function Users() {
  const [page, setPage] = useState(0);
  const [groupFilter, setGroupFilter] = useState("all"), [addingGroup, setAddingGroup] = useState(false);
  const { data } = useData("/admin/users?role=CUSTOMER&page=" + page + (groupFilter === "all" ? "" : "&groupId=" + encodeURIComponent(groupFilter))),
    { data: groups } = useData("/admin/config/groups");
  const { mutate, notify, session, online } = useApp();
  const [selected, setSelected] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  return (
    <>
      <Heading
        title="Khách hàng"
        sub="Phân nhóm khách hàng, khóa và mở tài khoản. Mọi thay đổi đều được ghi lịch sử."
      >
        {session.user.role === "ADMIN" && <button className="primary" disabled={!online} onClick={() => setAddingGroup(value => !value)}>Thêm nhóm khách hàng</button>}
      </Heading>
      {addingGroup && <QuickConfigCreate kind="groups" close={() => setAddingGroup(false)} />}
      <div className="panel customer-filters"><Field label="Lọc theo nhóm khách hàng"><select value={groupFilter} onChange={event => {setGroupFilter(event.target.value); setPage(0);}}><option value="all">Tất cả nhóm</option>{groups?.map((group: Row) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></Field></div>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Họ tên</th>
              <th>Liên hệ</th>
              <th>Nhóm khách hàng</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.map((u: Row) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.display_name}</strong>
                  <div className="product-subtitle">
                    {({ADMIN:"Người quản trị",SELLER:"Người bán",SHIPPER:"Người giao hàng",CUSTOMER:"Khách hàng"} as Row)[u.role]}
                  </div>
                </td>
                <td>
                  {u.phone_e164}
                  <div className="muted">{u.email_normalized}</div>
                </td>
                <td>{u.role !== "CUSTOMER" ? ({ADMIN:"Người quản trị",SELLER:"Người bán",SHIPPER:"Người giao hàng"} as Row)[u.role] : groups?.find((g: Row) => g.id === u.group_id)?.name ?? "Chưa phân nhóm"}</td>
                <td>
                  <Status value={u.status} />
                </td>
                <td>
                  <button
                    className="small"
                    disabled={
                      u.id === session.user.id || u.status === "DELETED"
                    }
                    onClick={() => setSelected({ ...u, groupId: u.group_id })}
                  >
                    Quản lý
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="toolbar">
        <button disabled={!page} onClick={() => setPage(page - 1)}>
          Trang trước
        </button>
        <button
          disabled={!data || data.length < 50}
          onClick={() => setPage(page + 1)}
        >
          Trang sau
        </button>
      </div>
      {selected && (
        <Modal
          title={"Quản lý · " + selected.display_name}
          close={() => setSelected(null)}
        >
          <div className="notice warn">
            Thay đổi nhóm hoặc trạng thái sẽ thu hồi các phiên đang đăng nhập
            của tài khoản này.
          </div>
          <form
            className="form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (
                selected.status === "DELETED" &&
                !confirm(
                  "Xóa mềm tài khoản? Không tái sử dụng số điện thoại cũ.",
                )
              )
                return;
              setBusy(true);
              try {
                await mutate(
                  "/admin/users/" + selected.id,
                  {
                    expectedVersion: String(selected.version),
                    groupId: selected.groupId,
                    status: selected.status,
                  },
                  "PATCH",
                );
                setSelected(null);
                notify("Đã cập nhật và thu hồi phiên cũ");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Nhóm khách hàng">
              {selected.role !== "CUSTOMER" ? <input value={({ADMIN:"Người quản trị",SELLER:"Người bán",SHIPPER:"Người giao hàng"} as Row)[selected.role]} readOnly /> : <select
                value={selected.groupId}
                onChange={(e) =>
                  setSelected({ ...selected, groupId: e.target.value })
                }
              >
                {groups
                  ?.filter((g: Row) => g.active)
                  .map((g: Row) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
              </select>}
            </Field>
            <Field label="Trạng thái">
              <select
                value={selected.status}
                onChange={(e) =>
                  setSelected({ ...selected, status: e.target.value })
                }
              >
                {["ACTIVE", "LOCKED", "DELETED"].map((s) => (
                  <option key={s} value={s}>
                    {statuses[s]}
                  </option>
                ))}
              </select>
            </Field>
            <button className="primary" disabled={!online || busy}>
              Lưu thay đổi
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

type ConfigField = [string, string, string, string?];
const configSpecs: Record<string, { title: string; fields: ConfigField[] }> = {
  groups: {
    title: "Nhóm khách hàng",
    fields: [
      ["code", "Mã nhóm", "text"],
      ["name", "Tên nhóm", "text"],
    ],
  },
  categories: { title: "Danh mục", fields: [["name", "Tên danh mục", "text"]] },
  units: {
    title: "Đơn vị",
    fields: [
      ["code", "Mã đơn vị", "text"],
      ["label", "Tên hiển thị", "text"],
    ],
  },
  policies: {
    title: "Chính sách giao",
    fields: [
      ["groupId", "Nhóm khách hàng", "select", "groups"],
      ["minimumSubtotal", "Tiền hàng tối thiểu (đ)", "number"],
      ["shippingFee", "Phí cơ bản (đ)", "number"],
      ["pricingMode", "Cách tính phí", "select", "pricingModes"],
      ["perKmFee", "Phí / km trong mốc đầu (đ)", "number"],
      ["distanceRounding", "Làm tròn khoảng cách", "select", "distanceRoundings"],
      ["feeRoundingStep", "Làm tròn tiền lên bội số (đ)", "number"],
      ["distanceEnabled", "Bật giao theo khoảng cách", "checkbox"],
      ["includedKm", "Mốc km đầu", "number"],
      ["extraKmFee", "Phí mỗi km vượt (đ)", "number"],
      ["maxDistanceKm", "Khoảng cách tối đa (km)", "number"],
    ],
  },
  "pickup-slots": {
    title: "Điểm nhận tập trung",
    fields: [
      ["name", "Tên điểm nhận", "text"],
      ["addressLine", "Địa chỉ nhận tập trung", "text"],
    ],
  },
  "moderation-rules": {
    title: "Từ cấm",
    fields: [
      ["phrase", "Từ / cụm từ", "text"],
      ["matchMode", "Cách khớp", "select", "matchModes"],
    ],
  },
};
const snake = (s: string) => s.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());
function Configuration() {
  const {session: configSession} = useApp();
  const [kind, setKind] = useState("groups"),
    [form, setForm] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const { data } = useData("/admin/config/" + kind),
    { data: groups } = useData("/admin/config/groups");
  const { mutate, online, notify } = useApp();
  const spec = configSpecs[kind];
  const options: Record<string, Row[]> = {
    groups: groups ?? [],
    pricingModes: [
      { id: "BASE_PLUS_EXTRA", name: "Phí cơ bản + km vượt" },
      { id: "TIERED_KM", name: "Theo km, hai mức giá" },
    ],
    distanceRoundings: [
      { id: "EXACT", name: "Theo quãng đường thực tế" },
      { id: "CEIL_KM", name: "Làm tròn lên km" },
    ],
    matchModes: [
      { id: "TOKEN", name: "Từ nguyên vẹn" },
      { id: "PHRASE", name: "Cụm từ" },
    ],
  };
  const isEnabled = (value: unknown) => value === true || value === 1 || value === "1";
  const edit = (row?: Row) => {
    const f: Row = {
      id: row?.id,
      version: row?.version,
      active: row ? isEnabled(row.active) : true,
    };
    for (const [key, , type, source] of spec.fields) {
      let v = row?.[key === "phrase" ? "phrase_normalized" : snake(key)];
      if (type === "datetime-local" && v) v = v.slice(0, 16);
      f[key] =
        type === "checkbox" ? isEnabled(v) : v ??
        (type === "checkbox"
          ? false
          : type === "select"
            ? options[source!]?.[0]?.id
            : type === "number"
              ? "0"
              : "");
      if (kind === "policies" && key === "maxDistanceKm" && f.pricingMode === "TIERED_KM" && v == null) f[key] = "";
      if (key === "feeRoundingStep" && v == null) f[key] = "1";
    }
    if (kind === "pickup-slots") f.allowedGroupIds = row?.allowed_group_ids ?? null;
    setForm(f);
  };
  const deactivateConfig = async (row: Row) => {
    const label = row.name ?? row.label ?? row.phrase_normalized ?? spec.title.toLowerCase();
    const impact = kind === "groups"
      ? " Khách thuộc nhóm này sẽ không còn thấy món giới hạn theo nhóm."
      : kind === "pickup-slots"
        ? " Khách sẽ không thể chọn điểm này cho đơn mới."
        : "";
    if (
      !window.confirm(
        `Xóa “${label}” khỏi danh sách đang dùng?${impact} Lịch sử vẫn được giữ.`,
      )
    )
      return;
    setBusy(true);
    try {
      await mutate(
        "/admin/config/" + kind + "/" + row.id,
        { expectedVersion: String(row.version) },
        "DELETE",
      );
      notify("Đã ngừng sử dụng cấu hình");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Heading
        title="Cấu hình vận hành"
        sub="Quản lý nhóm, chính sách giao, danh mục và kiểm duyệt nội dung."
      />
      <WarehouseSettings />
      {configSession.user.role === "ADMIN" && <VerifiedLocations />}
      <div className="tabs">
        {Object.entries(configSpecs).filter(([id])=>configSession.user.role==="ADMIN" || id!=="moderation-rules").map(([id, s]) => (
          <button
            key={id}
            className={kind === id ? "active" : ""}
            onClick={() => {
              setKind(id);
              setForm(null);
            }}
          >
            {s.title}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <h2>{spec.title}</h2>
        <button className="primary" disabled={!online} onClick={() => edit()}>
          <Icon icon={faPlus} /> Thêm
        </button>
      </div>
      {kind === "policies" && <p className="muted">Mỗi nhóm khách có một chính sách giao riêng đang dùng. Phí dựa trên quãng đường từ kho đến địa chỉ nhận.</p>}
      {kind === "pickup-slots" && <p className="muted">Nhận từ 17:00–18:00, giờ Việt Nam. Đặt trước 17:00 để nhận trong ngày.</p>}
      {kind === "groups" && (
        <p className="muted">
          Ngừng dùng sẽ ẩn món khỏi nhóm đó nhưng vẫn giữ đơn cũ. Nhóm Người đi
          làm là mặc định đăng ký.
        </p>
      )}
      <div className="panel table-scroll configuration-table-wrap">
        <table className="configuration-table">
          <thead>
            <tr>
              {spec.fields.map(([key, label]) => (
                <th key={key}>{label}</th>
              ))}
              <th>Hiệu lực</th>
              <th className="configuration-actions">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((row: Row) => (
              <tr key={row.id}>
                {spec.fields.map(([key, , type, source]) => {
                  const value =
                    row[key === "phrase" ? "phrase_normalized" : snake(key)];
                  return (
                    <td key={key}>
                      {type === "select"
                        ? (options[source!]?.find((o) => o.id === value)
                            ?.name ?? value)
                        : type === "datetime-local"
                          ? date(value)
                          : type === "checkbox"
                            ? isEnabled(value) ? "Bật" : "Tắt"
                            : kind === "policies" && key === "maxDistanceKm" && row.pricing_mode === "TIERED_KM" && value == null
                              ? "Không giới hạn"
                              : String(value ?? "")}
                    </td>
                  );
                })}
                <td><span className={"status " + (row.active != null && !isEnabled(row.active) ? "INACTIVE" : "ACTIVE")}>{row.active != null && !isEnabled(row.active) ? "Tắt" : "Đang dùng"}</span></td>
                <td className="configuration-actions">
                  <div className="actions">
                    <button className="small" disabled={!online || busy} onClick={() => edit(row)}>
                      Sửa
                    </button>
                    {isEnabled(row.active) && !(kind === "groups" && row.code === "WORKER") && (
                      <button
                        className="small danger"
                        disabled={!online || busy}
                        onClick={() => deactivateConfig(row)}
                      >
                        Xóa
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.length === 0 && <Empty title="Chưa có cấu hình" />}
      </div>
      {form && (
        <Modal
          title={(form.id ? "Sửa " : "Thêm ") + spec.title.toLowerCase()}
          close={() => setForm(null)}
        >
          <form
            className="form form-grid"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                const b: Row = {
                  ...form,
                  expectedVersion: String(form.version ?? ""),
                };
                for (const [key, , type] of spec.fields) {
                  if (type === "datetime-local") b[key] = form[key] + ":00Z";
                  if (type === "checkbox") b[key] = isEnabled(form[key]);
                }
                await mutate(
                  "/admin/config/" + kind + (form.id ? "/" + form.id : ""),
                  b,
                  form.id ? "PATCH" : "POST",
                );
                setForm(null);
                notify("Đã lưu cấu hình");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            {kind === "pickup-slots" && <AudienceFields groups={groups ?? []} value={form.allowedGroupIds ?? null}
              onChange={allowedGroupIds => setForm({...form,allowedGroupIds})} legend="Nhóm được chọn điểm nhận" />}
            {kind === "policies" && form.pricingMode === "TIERED_KM" && (
              <p className="field-hint wide">Mốc km đầu quyết định khi nào đổi giá / km. Khoảng cách tối đa là giới hạn nhận giao. Tổng phí được làm tròn lên theo bội số tiền đã chọn.</p>
            )}
            {spec.fields.map(([key, label, type, source]) => (
              <Field key={key} label={label}>
                {type === "checkbox" ? (
                  <input
                    type="checkbox"
                    checked={!!form[key]}
                    onChange={(e) =>
                      setForm({ ...form, [key]: e.target.checked })
                    }
                  />
                ) : type === "select" ? (
                  <select
                    required
                    value={form[key] ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, [key]: e.target.value })
                    }
                  >
                    {options[source!]?.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    required={key !== "description" && !(kind === "policies" && key === "maxDistanceKm" && form.pricingMode === "TIERED_KM")}
                    placeholder={kind === "policies" && key === "maxDistanceKm" && form.pricingMode === "TIERED_KM" ? "Để trống: không giới hạn" : undefined}
                    type={type}
                    disabled={
                      kind === "groups" &&
                      key === "code" &&
                      form.id &&
                      ["STUDENT", "WORKER"].includes(form.code)
                    }
                    title={
                      kind === "groups" &&
                      key === "code" &&
                      form.id &&
                      ["STUDENT", "WORKER"].includes(form.code)
                        ? "Mã hệ thống được giữ cố định để bảo vệ quy tắc giao hàng và đăng ký."
                        : undefined
                    }
                    min={type === "number" ? "0" : undefined}
                    step={type === "number" ? ["includedKm", "maxDistanceKm"].includes(key) ? "0.001" : "1" : undefined}
                    value={form[key] ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, [key]: e.target.value })
                    }
                  />
                )}
              </Field>
            ))}
            {kind !== "units" && (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={form.active}
                  onChange={(e) =>
                    setForm({ ...form, active: e.target.checked })
                  }
                />
                Đang sử dụng
              </label>
            )}
            <button className="primary" disabled={!online || busy}>
              Lưu cấu hình
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

function Audit() {
  const [kind, setKind] = useState("audit");
  const [startDate, setStartDate] = useState(vnDateOffset(vnDay(), -6));
  const [endDate, setEndDate] = useState(vnDay());
  const [range, setRange] = useState({start: vnDateOffset(vnDay(), -6), end: vnDay()});
  const [page, setPage] = useState(0);
  const {data: groups} = useData("/admin/config/groups");
  const { data, loading } = useData("/admin/" + (kind === "violations" ? "moderation/violations" : kind)
    + `?startDate=${range.start}&endDate=${range.end}&page=${page}`);
  const invalid = startDate > endDate;
  const value = (key: string, v: any): string => {
    if (v === null || v === undefined || v === "") return "Chưa có";
    if (key === "group_id") return groups?.find((g:Row) => g.id === v)?.name ?? String(v);
    if (key === "allowed_group_ids") return Array.isArray(v) ? v.map(id => groups?.find((g:Row) => g.id === id)?.name ?? id).join(", ") : "Tất cả nhóm";
    if (typeof v === "boolean") return v ? "Có" : "Không";
    if (key.endsWith("_at")) return date(v);
    if (key === "status") return statuses[v] ?? String(v);
    if (key === "audience_mode") return v === "MENU" ? "Nhóm chung của đợt" : "Tùy chỉnh từng sản phẩm";
    if (key.includes("price") || key.endsWith("fee") || key === "minimum_subtotal") return money(v);
    return typeof v === "object" ? JSON.stringify(v) : String(v);
  };
  return <>
    <Heading title="Nhật ký vận hành" sub="Theo dõi thao tác, người thực hiện và thay đổi. Phạm vi ngày tính theo giờ Việt Nam, gồm cả ngày kết thúc." />
    <div className="tabs">{[["audit","Thao tác quản trị"],["inventory-movements","Biến động kho"],["violations","Vi phạm nội dung"]].map(([id,label])=>
      <button key={id} className={id===kind?"active":""} onClick={()=>{setKind(id);setPage(0);}}>{label}</button>)}</div>
    <form className="toolbar audit-filter" onSubmit={e=>{e.preventDefault();if(!invalid){setRange({start:startDate,end:endDate});setPage(0);}}}>
      <Field label="Từ ngày"><input type="date" required value={startDate} max={endDate || undefined} onChange={e=>setStartDate(e.target.value)} /></Field>
      <Field label="Đến ngày"><input type="date" required value={endDate} min={startDate || undefined} onChange={e=>setEndDate(e.target.value)} /></Field>
      <button className="primary" disabled={!startDate || !endDate || invalid}>Lọc nhật ký</button>
      <button type="button" onClick={()=>{const d=vnDay();setStartDate(d);setEndDate(d);setRange({start:d,end:d});setPage(0);}}>Hôm nay</button>
    </form>
    {invalid && <p className="notice error" role="alert">Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.</p>}
    <p className="muted">Từ {range.start} đến {range.end} · Trang {page+1} · Tối đa 100 bản ghi mỗi trang</p>
    <div className="panel table-scroll" style={{marginTop:14}}><table className="audit-table"><thead><tr>
      <th>Thời điểm</th><th>Hoạt động</th><th>Người thực hiện</th><th>Đối tượng</th><th>Chi tiết</th>
    </tr></thead><tbody>{data?.map((r:Row)=><tr key={r.id}>
      <td className="date">{date(r.created_at)}</td><td><strong>{activityLabel(r)}</strong></td><td>{r.actor_name}</td>
      <td>{r.entity_name ?? (kind==="violations" ? "Nội dung người dùng" : "Bản ghi")}
        <div className="product-subtitle">{(r.entity_id ?? r.order_id ?? r.reference_id ?? "").slice(0,8)}</div></td>
      <td className="audit-detail">{kind==="violations" ? <><p>Trường: {r.field_name}</p><p>{r.original_restricted} → {r.sanitized}</p></>
        : kind==="inventory-movements" ? <><p>Biến động: {qty(r.quantity_delta)} · Tồn sau: {qty(r.balance_after)}</p><p>{r.reason}</p></>
        : <><ul className="audit-changes">{changedFields(r).map(key=><li key={key}><strong>{activityFields[key]}: </strong>{value(key,r.before_data?.[key])} → {value(key,r.after_data?.[key])}</li>)}</ul>
            {!changedFields(r).length && <p>Đã ghi nhận thay đổi. Mở dữ liệu gốc để xem đầy đủ.</p>}
            <details><summary>Xem dữ liệu gốc</summary><pre>{JSON.stringify({truoc:r.before_data,sau:r.after_data},null,2)}</pre></details></>}
      </td>
    </tr>)}</tbody></table>{loading && <div className="spinner">Đang tải nhật ký…</div>}{data?.length===0 && <Empty title="Không có bản ghi trong phạm vi ngày này" />}</div>
    <div className="toolbar"><button disabled={page===0 || loading} onClick={()=>setPage(p=>p-1)}>Trang trước</button><button disabled={loading || !data || data.length<100} onClick={()=>setPage(p=>p+1)}>Trang sau</button></div>
  </>;
}

const vnDay = (d = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
const vnDateOffset = (day: string, offset: number) => {
  const date = new Date(day + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
};
const goTo = (tab: string) =>
  window.dispatchEvent(new CustomEvent("ro:navigate", { detail: tab }));
const milli = (n: unknown) => {
  const [a, b = ""] = String(n).split(".");
  return BigInt(a || "0") * BigInt(1000) + BigInt(b.padEnd(3, "0").slice(0, 3));
};
const fromMilli = (n: bigint) =>
  `${n / BigInt(1000)}.${String(n % BigInt(1000)).padStart(3, "0")}`;

function AudienceFields({
  value,
  onChange,
  groups,
  legend = "Nhóm được phép mua",
}: {
  value: string[] | null;
  onChange: (v: string[] | null) => void;
  groups: Row[];
  legend?: string;
}) {
  return (
    <fieldset className="audience">
      <legend>{legend}</legend>
      <label className="check">
        <input
          type="checkbox"
          checked={value === null}
          onChange={(e) => onChange(e.target.checked ? null : [])}
        />
        Tất cả nhóm
      </label>
      {value !== null &&
        groups
          .filter((g) => g.active)
          .map((g) => (
            <label className="check" key={g.id}>
              <input
                type="checkbox"
                checked={value.includes(g.id)}
                onChange={(e) =>
                  onChange(
                    e.target.checked
                      ? [...value, g.id]
                      : value.filter((id) => id !== g.id),
                  )
                }
              />
              {g.name}
            </label>
          ))}
    </fieldset>
  );
}

const locationMatchLabels: Record<string, string> = {
  VERIFIED: "Địa chỉ quản trị đã xác nhận",
  HOUSE_NUMBER: "Khớp số nhà và tên đường — kiểm tra lại ghim/khu vực",
  NEARBY: "Địa điểm gần đúng — chưa khớp đủ số nhà",
  STREET: "Chỉ tìm thấy đường/khu vực — cần chỉnh ghim",
};

function VerifiedLocations() {
  const { data } = useData("/admin/maps/verified");
  const { mutate, online, notify } = useApp();
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  return <section className="panel verified-locations">
    <div className="panel-head">
      <div><h2>Địa chỉ công cộng đã xác nhận</h2><p className="muted">Bổ sung số nhà, cổng trường, tòa nhà còn thiếu trên bản đồ.</p></div>
      <button aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Thu gọn" : "Quản lý địa chỉ"}</button>
    </div>
    {expanded && <>
      <p className="muted">Chỉ thêm địa điểm công cộng đã kiểm tra. Địa chỉ riêng của khách không tự động đưa vào danh sách này.</p>
      <button className="primary" disabled={!online || busy} onClick={() => setForm({ label: "", houseNumber: "", street: "", aliasesText: "" })}>Thêm địa chỉ công cộng</button>
      {!data ? <p>Đang tải…</p> : !data.length ? <p className="muted">Chưa có địa chỉ đã xác nhận.</p> : data.map((row: Row) => <div className="list-row" key={row.id}>
        <strong>{row.label}</strong><p className="muted">{row.aliases.join("; ")}</p>
        <div className="actions"><button disabled={!online || busy} onClick={() => setForm({ ...row, houseNumber: row.house_number, aliasesText: row.aliases.join("\n") })}>Sửa địa chỉ</button>
          <button disabled={!online || busy} onClick={async () => {
            if (!window.confirm("Ngừng gợi ý địa chỉ này? Các đơn và địa chỉ khách đã lưu giữ nguyên.")) return;
            setBusy(true); try { await mutate("/admin/maps/verified/" + row.id, { expectedVersion: row.version }, "DELETE"); } catch {} finally { setBusy(false); }
          }}>Ngừng gợi ý</button></div>
      </div>)}
    </>}
    {form && <Modal title={form.id ? "Sửa địa chỉ công cộng" : "Thêm địa chỉ công cộng"} close={() => setForm(null)}>
      <form className="form form-grid" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true);
        try {
          await mutate("/admin/maps/verified" + (form.id ? "/" + form.id : ""), {
            label: form.label, houseNumber: form.houseNumber, street: form.street,
            aliases: form.aliasesText.split("\n").map((v: string) => v.trim()).filter(Boolean),
            locationToken: form.locationToken, expectedVersion: form.version,
          }, form.id ? "PATCH" : "POST"); setForm(null); notify("Đã lưu địa chỉ công cộng");
        } catch {} finally { setBusy(false); }
      }}>
        <Field label="Tên và địa chỉ hiển thị" wide><input required maxLength={500} value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
        <Field label="Số nhà"><input maxLength={40} value={form.houseNumber} onChange={(e) => setForm({ ...form, houseNumber: e.target.value })} /></Field>
        <Field label="Tên đường"><input maxLength={200} value={form.street} onChange={(e) => setForm({ ...form, street: e.target.value })} /></Field>
        <Field label="Tên gọi / địa chỉ khác (mỗi dòng một tên)" wide><textarea value={form.aliasesText} onChange={(e) => setForm({ ...form, aliasesText: e.target.value })} /></Field>
        <div className="wide"><LocationPicker initial={form.label} initialPoint={form.latitude != null ? { latitude: Number(form.latitude), longitude: Number(form.longitude) } : null}
          onSelect={(loc) => setForm((f: Row | null) => f ? { ...f, locationToken: loc.locationToken, locationDirty: true } : f)} /></div>
        <button className="primary" disabled={!online || busy || ((!form.id || form.locationDirty) && !form.locationToken)}>Lưu địa chỉ công cộng</button>
      </form>
    </Modal>}
  </section>;
}

function LocationPicker({ onSelect, initial = "", initialPoint = null }: {
  onSelect: (v: Row) => void; initial?: string; initialPoint?: MapPoint | null;
}) {
  const [query, setQuery] = useState(initial.slice(0, 200));
  const [results, setResults] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [searched, setSearched] = useState(false), [mapOpen, setMapOpen] = useState(false);
  const [point, setPoint] = useState<MapPoint | null>(initialPoint);
  const [confirmed, setConfirmed] = useState(false), [approximate, setApproximate] = useState(false);
  const [matchType, setMatchType] = useState(""), [source, setSource] = useState("");
  const { online } = useApp();
  const { data: mapConfig } = useData("/maps/config");
  const movePoint = (next: MapPoint) => {
    setPoint(next); setConfirmed(false); setApproximate(false); setMatchType(""); setSource(""); setError(""); onSelect({ locationToken: null });
  };
  return <div className="location-picker">
    <label>Tìm địa danh hoặc đường gần điểm nhận
      <input value={query} disabled={busy} maxLength={200} placeholder="Tên đường, tòa nhà, trường học…" onChange={(e) => {
        setQuery(e.target.value); setSearched(false); setError(""); setResults([]);
        setPoint(null); setConfirmed(false); setMatchType(""); setSource(""); setApproximate(false);
        onSelect({ locationToken: null });
      }} />
    </label>
    <div className="actions">
      <button type="button" disabled={!online || busy || query.trim().length < 3} onClick={async () => {
        setBusy(true); setError("");
        setResults([]);
        try { setResults(await api("/maps/search?q=" + encodeURIComponent(query.trim()))); setSearched(true); }
        catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>{busy ? "Đang xử lý…" : "Tìm địa chỉ"}</button>
      <button type="button" onClick={() => setMapOpen(!mapOpen)}>{mapOpen ? "Ẩn bản đồ" : "Chọn trực tiếp trên bản đồ"}</button>
    </div>
    <div role="status">
      {error && <p className="notice warn">{error}</p>}
      {!busy && searched && !error && results.length === 0 && <p className="notice">Chưa có kết quả phù hợp. Bạn có thể chọn trực tiếp trên bản đồ; không cần chọn một địa chỉ sai.</p>}
    </div>
    {!!results.length && <div className="location-results">{results.map((r) => <button type="button" key={r.id} disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        const loc = await api("/maps/place?id=" + encodeURIComponent(r.id));
        setPoint({ latitude: Number(loc.latitude), longitude: Number(loc.longitude) });
        setApproximate(!!loc.approximate); setMatchType(loc.matchType ?? "NEARBY"); setSource(loc.source ?? "NOMINATIM"); setMapOpen(true); setResults([]); setSearched(false);
        setConfirmed(false); onSelect({ locationToken: null });
      } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}>{r.label}<small className="location-result-hint">{r.source === "VIETMAP" ? "Kiểm tra vị trí và số nhà" : (locationMatchLabels[r.matchType] ?? (r.approximate ? locationMatchLabels.STREET : locationMatchLabels.NEARBY))} · {r.source === "VIETMAP" ? "VIETMAP" : r.source === "GOOGLE" ? "Google Maps" : r.source === "LOCAL" ? "Danh sách công cộng" : r.source === "PHOTON" ? "Photon / OpenStreetMap" : "Nominatim / OpenStreetMap"}</small></button>)}</div>}
    {mapOpen && <>
      {matchType && !approximate && <p className="notice">{source === "VIETMAP" ? "Kiểm tra số nhà và vị trí trước khi xác nhận." : locationMatchLabels[matchType]}{source === "LOCAL" && ". Vẫn kiểm tra cổng/điểm nhận trước khi xác nhận."}</p>}
      {approximate && <p className="notice warn">Kết quả này là đoạn đường/khu vực, chưa phải số nhà. Hãy đặt lại ghim trước khi xác nhận.</p>}
      {mapConfig ? mapConfig.provider === "google" ? <GooglePointMap value={point} center={mapConfig.center} browserKey={mapConfig.browserKey} disabled={busy || !online} onChange={movePoint} /> : <PointMap value={point} center={mapConfig.center} tileUrl={mapConfig.tileUrl} disabled={busy || !online} onChange={movePoint} /> : <p>Đang tải cấu hình bản đồ…</p>}
      {point && <p className="muted">Điểm đã chọn: {point.latitude.toFixed(6)}, {point.longitude.toFixed(6)}</p>}
      <button type="button" className="primary" disabled={!point || busy || !online} onClick={async () => {
        if (!point) return;
        setBusy(true); setError("");
        try {
          const loc = await api("/maps/pin", "POST", { ...point, address: query.trim() || "Điểm nhận đã chọn trên bản đồ" });
          onSelect(loc); setConfirmed(true); setApproximate(false);
        } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>Xác nhận điểm nhận này</button>
    </>}
    {confirmed && <p className="notice" role="status">Đã xác nhận điểm trên bản đồ. Lưu thay đổi để hoàn tất.</p>}
    <p className="muted osm-attribution">{mapConfig?.provider === "vietmap" ? "Địa chỉ tìm bằng VIETMAP. Bản đồ nền © OpenStreetMap contributors. Vui lòng kiểm tra vị trí trước khi xác nhận." : mapConfig?.provider === "google" ? "Google Maps · Kiểm tra vị trí trên bản đồ trước khi xác nhận." : <>OpenStreetMap có thể thiếu số nhà. Tìm địa danh gần đó rồi chọn ghim; địa chỉ chi tiết vẫn nhập riêng bên dưới. Tìm kiếm qua Photon/Nominatim và tải bản đồ sử dụng dịch vụ công cộng; chỉ dùng địa điểm thử nghiệm.</>}</p>
  </div>;
}

function WarehouseSettings() {
  const { data: warehouse } = useData("/admin/warehouse");
  const { mutate, online, notify, session } = useApp();
  const [location, setLocation] = useState<Row | null>(null);
  return (
    <section className="panel warehouse">
      <h2>Kho xuất hàng</h2>
      <p>{warehouse?.address || "Chưa chọn địa chỉ lấy hàng"}</p>
      <p className="muted">
        {warehouse?.configured
          ? "Đã xác nhận vị trí kho"
          : "Cần xác nhận vị trí kho để tính phí giao riêng."}
      </p>
      <LocationPicker
        initial={warehouse?.address ?? (session.user.role === "ADMIN" ? "96A Trần Phú, Hà Đông, Hà Nội" : "")}
        initialPoint={warehouse?.latitude != null ? { latitude: Number(warehouse.latitude), longitude: Number(warehouse.longitude) } : null}
        onSelect={setLocation}
      />
      <button
        disabled={!online || !location?.locationToken || !warehouse}
        onClick={async () => {
          try {
            await mutate(
              "/admin/warehouse",
              {
                locationToken: location?.locationToken,
                expectedVersion: warehouse.version,
              },
              "PATCH",
            );
            setLocation(null);
            notify("Đã lưu vị trí kho");
          } catch {}
        }}
      >
        Lưu vị trí kho
      </button>
    </section>
  );
}

function ProductImageGallery({
  images,
  name,
}: {
  images: unknown[];
  name: string;
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [enlarged, setEnlarged] = useState(false);
  const [failed, setFailed] = useState(false);
  const imageSources = Array.isArray(images)
    ? images.map(productImageSrc).filter(Boolean)
    : [];
  if (!imageSources.length)
    return (
      <div className="daily-product-gallery">
        <div className="daily-product-image-main daily-product-image-empty">
          <Icon icon={faImage} aria-hidden="true" />
          <span>Chưa có ảnh sản phẩm</span>
        </div>
      </div>
    );

  const activeIndex = Math.min(selectedIndex, imageSources.length - 1);
  const imageUrl = imageSources[activeIndex];
  const chooseImage = (index: number) => {
    setSelectedIndex(index);
    setFailed(false);
  };
  const imageContent = (className: string) =>
    failed ? (
      <div className="product-image-load-failed">
        <Icon icon={faImage} aria-hidden="true" />
        <span>Không tải được ảnh</span>
      </div>
    ) : (
      <img
        className={className}
        src={imageUrl}
        alt={`${name} · ảnh ${activeIndex + 1}`}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  return (
    <>
      <div className="daily-product-gallery">
        <button
          type="button"
          className="daily-product-image-main"
          onClick={() => setEnlarged(true)}
          aria-label={`Xem ảnh lớn của ${name}`}
        >
          {imageContent("")}
        </button>
        {imageSources.length > 1 && (
          <div className="product-image-thumbs" role="group" aria-label={`Ảnh ${name}`}>
            {imageSources.map((source, index) => (
              <button
                type="button"
                key={source}
                aria-label={`Chọn ảnh ${index + 1} của ${name}`}
                aria-pressed={index === activeIndex}
                onClick={() => chooseImage(index)}
              >
                <img src={source} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        )}
      </div>
      {enlarged && (
        <Modal
          title={`Ảnh sản phẩm · ${name}`}
          close={() => setEnlarged(false)}
        >
          <div className="product-image-viewer">
            <div className="product-image-viewer-stage">
              {imageContent("")}
            </div>
            {imageSources.length > 1 && (
              <div className="product-image-thumbs product-image-viewer-thumbs" role="group" aria-label={`Chọn ảnh ${name}`}>
                {imageSources.map((source, index) => (
                  <button
                    type="button"
                    key={source}
                    aria-label={`Chọn ảnh ${index + 1} của ${name}`}
                    aria-pressed={index === activeIndex}
                    onClick={() => chooseImage(index)}
                  >
                    <img src={source} alt="" loading="lazy" />
                  </button>
                ))}
              </div>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

function DailyCatalog({ mode }: { mode: "catalog" | "checkout" }) {
  const { session, online, mutate, notify, reload } = useApp();
  const [catalogView, setCatalogView] = useState("OPEN");
  const promoKey = "ro:menu-promo-dismissed:" + session.user.id;
  const [promoClosed, setPromoClosed] = useState(false);
  const [promoIds, setPromoIds] = useState<string[] | null>(null);
  useEffect(() => { setPromoClosed(sessionStorage.getItem(promoKey) === "1"); }, [promoKey]);

  const { data: upcoming } = useData("/catalog/upcoming");
  const { data: allOffers } = useData("/catalog/offers");
  const { data: feed } = useData("/feed");
  const { data: checkoutConfig } = useData("/checkout/config");
  const { data: addresses } = useData("/me/addresses");
  const offers = allOffers;
  useEffect(() => {
    if (!offers || promoIds !== null) return;
    const eligible = offers.filter((o: Row) => milli(o.available_qty) > BigInt(0)).map((o: Row) => o.id);
    if (!eligible.length) return;
    for (let i = eligible.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [eligible[i], eligible[j]] = [eligible[j], eligible[i]];
    }
    setPromoIds(eligible.slice(0, 5));
  }, [offers, promoIds]);
  const promoOffers = (promoIds ?? []).map(id => offers?.find((o: Row) => o.id === id))
    .filter((o: Row | undefined): o is Row => !!o && milli(o.available_qty) > BigInt(0));
  const [wideScreen, setWideScreen] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1100px)");
    const update = () => setWideScreen(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const cartKey = "ro-daily-cart-" + session.user.id;
  const [previousFee, setPreviousFee] = useState<string | null>(null);
  const [allCart, setAllCart] = useState<Row[]>(() => readCart<Row>(cartKey)),
    [requestedView, setRequestedView] = useState<"cart" | "checkout" | null>(
      null,
    ),
    [address, setAddress] = useState(""),
    [slotId, setSlotId] = useState(""),
    [note, setNote] = useState(""),
    [quote, setQuote] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [nowMs, setNowMs] = useState(Date.now()),
    [search, setSearch] = useState(""),
    [category, setCategory] = useState("ALL");
  const cart = allCart;
  const setCart = setAllCart;
  const deliveryQuery = new URLSearchParams();
  for (const id of [...new Set<string>(cart.map(item => String(item.menu_id)))].sort()) {
    if (id && id !== "undefined" && id !== "null") deliveryQuery.append("menuId", id);
  }
  const { data: delivery } = useData("/delivery/options?" + deliveryQuery);
  const [deliveryMethod, setDeliveryMethod] = useState("INDIVIDUAL");
  const [paymentMethod,setPaymentMethod] = useState("COD");
  const [quantityDrafts, setQuantityDrafts] = useState<Record<string, string>>({});
  const view =
    mode === "checkout" && requestedView === null ? "checkout" : requestedView;
  const setView = setRequestedView;
  const cartMotionKey = cart.map(c => `${c.id}:${c.quantity}`).join("|");
  const previousCartMotionKey = useRef(cartMotionKey);
  useEffect(() => {
    const changed = previousCartMotionKey.current !== cartMotionKey;
    previousCartMotionKey.current = cartMotionKey;
    if (!changed || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const animation = document.querySelector(".cart-page-button")?.animate(
      [{ transform: "scale(1)" }, { transform: "scale(1.035)" }, { transform: "scale(1)" }],
      { duration: 220, easing: "ease-out" },
    );
    return () => animation?.cancel();
  }, [cartMotionKey]);
  const chosenAddress =
    (addresses ?? []).find((a: Row) => a.id === address) ?? addresses?.[0];
  const policy = delivery?.policies?.[0];
  const slots: Row[] = delivery?.pickupSlots ?? [];
  const slot = slots.find((s: Row) => s.id === slotId) ?? slots[0];
  const fingerprint = JSON.stringify([
    cart.map((c) => [c.id, c.quantity, c.price_version, allOffers?.find((o: Row) => o.id === c.id)?.vat_rate]),
    chosenAddress?.id,
    chosenAddress?.version,
    policy?.id,
    policy?.version,
    checkoutConfig?.vatVersion,
    deliveryMethod,
    slot?.id,
    slot?.version,
    slot?.starts_at,
  ]);
  useEffect(() => {
    setConfirmed(false);
  }, [fingerprint, paymentMethod]);
  useEffect(() => {
    sessionStorage.setItem(cartKey, JSON.stringify(allCart));
  }, [allCart, cartKey]);
  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
      reload();
    }, 30000);
    const visible = () => {
      if (!document.hidden) reload();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload]);
  useEffect(() => {
    const handler = (e: Event) => {
      if ((e as CustomEvent).detail.path === "/orders") {
        setAllCart([]);
        setQuantityDrafts({});
        setView(null);
      }
    };
    window.addEventListener("ro:operation-resolved", handler);
    return () => window.removeEventListener("ro:operation-resolved", handler);
  }, []);
  const stale = cart.some(
    (c) =>
      !allOffers?.some(
        (o: Row) =>
          o.id === c.id &&
          o.price_version === c.price_version &&
          milli(o.available_qty) >= milli(c.quantity),
      ),
  );
  const subtotal = cart.reduce(
    (sum: bigint, c) => sum + lineMoney(c.unit_price, c.quantity),
    BigInt(0),
  );
  const vatRateFor = (item: Row) => Number(allOffers?.find((offer: Row) => offer.id === item.id)?.vat_rate ?? 0);
  const vatAmount = cart.reduce((sum, item) =>
    sum + (lineMoney(item.unit_price, item.quantity) * BigInt(Math.round(vatRateFor(item) * 100)) + 5000n) / 10000n, 0n);
  const quantityError = (c: Row, raw: string): string | null => {
    if (!raw.trim()) return "Nhập số lượng.";
    let normalized = raw.trim().replace(",", ".");
    if (normalized.startsWith(".")) normalized = "0" + normalized;
    if (!/^\d+(?:\.\d{0,3})?$/.test(normalized)) {
      return "Nhập số hợp lệ, tối đa 3 chữ số thập phân.";
    }
    const amount = milli(normalized);
    const step = milli(c.quantity_step);
    if (amount <= BigInt(0)) return "Số lượng phải lớn hơn 0.";
    if (amount < step) return `Số lượng tối thiểu là ${qty(c.quantity_step)} ${c.unit}.`;
    if (amount % step !== BigInt(0)) {
      return `Số lượng phải theo bước ${qty(c.quantity_step)} ${c.unit}.`;
    }
    const live = allOffers?.find((o: Row) => o.id === c.id);
    if (!live) return "Sản phẩm hiện không còn mở bán.";
    if (amount > milli(live.available_qty)) {
      return `Chỉ còn ${qty(live.available_qty)} ${c.unit}.`;
    }
    return null;
  };
  const invalidQuantity = cart.some((c) => {
    const draft = quantityDrafts[c.id];
    return draft !== undefined && quantityError(c, draft) !== null;
  });
  const quantityInputValue = (value: unknown) => {
    const [whole, fraction = ""] = String(value ?? "0").split(".");
    const trimmed = fraction.replace(/0+$/, "");
    return trimmed ? `${whole},${trimmed}` : whole;
  };
  const clearQuantityDraft = (id: string) =>
    setQuantityDrafts((old) => {
      if (!(id in old)) return old;
      const next = { ...old };
      delete next[id];
      return next;
    });
  const changeQuantityInput = (c: Row, raw: string) => {
    setQuantityDrafts((old) => ({ ...old, [c.id]: raw }));
    if (quantityError(c, raw)) return;
    let normalized = raw.trim().replace(",", ".");
    if (normalized.startsWith(".")) normalized = "0" + normalized;
    const amount = fromMilli(milli(normalized));
    setCart((old) => old.map((item) =>
      item.id === c.id ? { ...item, quantity: amount } : item,
    ));
  };
  const finishQuantityInput = (c: Row) => {
    const draft = quantityDrafts[c.id];
    if (draft !== undefined && !quantityError(c, draft)) clearQuantityDraft(c.id);
  };
  const quoteStale = !!quote && quote.fingerprint !== fingerprint;
  const expired = !!quote && new Date(quote.expiresAt).getTime() <= nowMs;
  const fee = deliveryMethod === "COLLECTIVE" && slot ? "0" : quote?.shippingFee;
  const categories: string[] = Array.from(
    new Set<string>(
      (offers ?? [])
        .map((o: Row) => String(o.category_name ?? "").trim())
        .filter(Boolean),
    ),
  ).sort((a, b) => a.localeCompare(b, "vi"));
  useEffect(() => {
    if (offers && category !== "ALL" && !offers.some((o: Row) => String(o.category_name ?? "").trim() === category)) {
      setCategory("ALL");
    }
  }, [offers, category]);
  const searchTerm = search.trim().toLocaleLowerCase("vi-VN");
  const filteredOffers = (offers ?? []).filter((o: Row) => {
    const matchesCategory =
      category === "ALL" || String(o.category_name ?? "").trim() === category;
    const searchable = [o.name, o.description, o.category_name]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase("vi-VN");
    return matchesCategory && (!searchTerm || searchable.includes(searchTerm));
  });
  const items = () =>
    cart.map((c) => ({
      offerId: c.id,
      quantity: c.quantity,
      expectedPriceVersion: String(c.price_version),
      expectedVatRate: vatRateFor(c),
    }));
  const add = (o: Row) => {
    clearQuantityDraft(o.id);
    const prev = allCart.find((c) => c.id === o.id);
    const quantity =
      (prev ? milli(prev.quantity) : BigInt(0)) + milli(o.quantity_step);
    if (quantity > milli(o.available_qty)) {
      notify("Số lượng vượt lượng còn trong kho", true);
      return;
    }
    setAllCart((old) => [...old.filter((c) => c.id !== o.id), { ...o, quantity: fromMilli(quantity) }]);
    setView("cart");
  };
  const adjust = (c: Row, delta: bigint) => {
    clearQuantityDraft(c.id);
    const quantity = milli(c.quantity) + delta;
    if (quantity <= BigInt(0)) {
      setCart((old) => old.filter((x) => x.id !== c.id));
      return;
    }
    const live = allOffers?.find((o: Row) => o.id === c.id);
    if (!live || quantity > milli(live.available_qty)) {
      notify("Lượng còn lại không đủ", true);
      return;
    }
    setCart((old) =>
      old.map((x) =>
        x.id === c.id ? { ...x, quantity: fromMilli(quantity) } : x,
      ),
    );
  };
  const submit = async () => {
    if (deliveryMethod === "INDIVIDUAL" ? !policy || !chosenAddress : !slot) return;
    setBusy(true);
    try {
      await mutate("/orders", {
        clientOrderId: crypto.randomUUID(),
        addressId: chosenAddress?.id,
        deliveryMethod,
        paymentMethod,
        vatVersion: checkoutConfig?.vatVersion,
        policyVersion: String(policy?.version ?? ""),
        pickupSlotId: slot?.id,
        pickupSlotVersion: String(slot?.version ?? ""),
        pickupStartsAt: slot?.starts_at,
        deliveryQuoteId: quote?.id,
        items: items(),
        note,
      });
      setAllCart([]);
      setQuantityDrafts({});
      setView(null);
      notify("Đã gửi đơn, đang chờ người bán duyệt");
      goTo("orders");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
    <section className="daily-catalog-layout">
      {mode === "checkout" ? (
        <Heading
          className="daily-checkout-heading"
          title="Thanh toán & đặt hàng"
          sub="Kiểm tra giỏ hàng, địa chỉ nhận và phí giao trước khi gửi đơn."
        >
          <button
            className="ghost"
            onClick={() => {
              setView(null);
              goTo("catalog");
            }}
          >
            Tiếp tục chọn món
          </button>
        </Heading>
      ) : (
        <>
          <Heading
            className="daily-catalog-heading"
            title="Menu hôm nay"
            sub={new Date().toLocaleDateString("vi-VN", {
              timeZone: "Asia/Ho_Chi_Minh",
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          >
            <button
              className="primary cart-page-button"
              aria-label="Mở trang thanh toán và giỏ hàng"
              onClick={() => {
                setView("checkout");
                goTo("checkout");
              }}
            >
              <Icon icon={faCartShopping} />
              <span>Giỏ hàng ({allCart.length})</span>
              {cart.length > 0 && <strong>{money(subtotal)}</strong>}
            </button>
          </Heading>
          {!promoClosed && promoOffers.length > 0 && <section className="menu-promotion" aria-label="Gợi ý sản phẩm đang mở bán">
            <div className="row-heading"><div><div className="eyebrow">Đang mở bán</div><h2>Gợi ý hôm nay</h2></div>
              <button className="ghost small" aria-label="Đóng gợi ý sản phẩm" onClick={() => { setPromoClosed(true); sessionStorage.setItem(promoKey, "1"); }}>✕</button>
            </div>
            <div className="promotion-products">{promoOffers.map((o: Row) => <article key={o.id} className="promotion-product">
              <div className="promotion-thumb"><Icon icon={faImage} aria-hidden="true" />{o.images?.length > 0 && <img src={productImageSrc(o.images[0])} alt={o.name} loading="lazy" onError={e => { e.currentTarget.style.display = "none"; }} />}
                {Number(o.list_price) > Number(o.unit_price) && Number(o.discount_percent) > 0 && <span className="promotion-discount">−{o.discount_percent}%</span>}
              </div>
              <strong className="promotion-name">{o.name}</strong>
              <div className="promotion-price">
                {Number(o.list_price) > Number(o.unit_price) && <del>{money(o.list_price)}</del>}
                <div><strong>{money(o.unit_price)}</strong> <span>/ {o.unit}</span></div>
              </div>
              <button className="small primary" aria-label={"Thêm " + o.name + " vào giỏ"} disabled={!online} onClick={() => add(o)}>Thêm vào giỏ</button>
            </article>)}</div>
          </section>}
          <p className="stock-note">
            Số lượng có hạn trong ngày. Đơn được giữ hàng sau khi người bán
            duyệt.
          </p>
        </>
      )}
      {mode === "checkout" ? null : !offers ? (
        <Empty title="Đang tải menu…" />
      ) : (
        <>
          <div className="tabs catalog-view-tabs" role="group" aria-label="Trạng thái mở bán">
            <button className={catalogView === "OPEN" ? "active" : ""} aria-pressed={catalogView === "OPEN"} onClick={() => setCatalogView("OPEN")}>Đang mở bán ({offers.length})</button>
            <button className={catalogView === "UPCOMING" ? "active" : ""} aria-pressed={catalogView === "UPCOMING"} onClick={() => setCatalogView("UPCOMING")}>Mặt hàng sắp mở bán ({upcoming?.length ?? 0})</button>
          </div>
          {catalogView === "OPEN" && offers.length > 0 && offers.every((o: Row) => milli(o.available_qty) <= BigInt(0)) &&
            <div className="notice" role="status"><strong>Đã bán hết</strong> · Các mặt hàng dành cho bạn hiện đã hết. Bạn có thể mua tiếp khi kho được bổ sung.</div>}
          {catalogView === "UPCOMING" ? <>
            <p className="muted">Sản phẩm chưa được đưa vào đợt bán. Theo dõi để nhận thông báo khi mở bán.</p>
            {!upcoming ? <Empty title="Đang tải sản phẩm…" /> : !upcoming.length ? <Empty title="Chưa có mặt hàng sắp mở bán" /> :
              <div className="daily-products">{upcoming.map((o: Row) => <article className="daily-product" key={o.product_id}>
                <ProductImageGallery images={o.images ?? []} name={o.name} />
                <div className="daily-product-info"><h2>{o.name}</h2><p>{o.description}</p><p>Đơn vị: {o.unit}</p></div>
                <div className="daily-product-buy"><span className="status SCHEDULED">Chưa mở bán</span>
                  <button disabled={!online} onClick={async () => { try { await mutate("/subscriptions/products/" + o.product_id, {}, o.subscribed ? "DELETE" : "POST"); } catch {} }}>{o.subscribed ? "Đang theo dõi" : "Báo khi mở bán"}</button>
                </div>
              </article>)}</div>}
          </> : <>
          <div className="daily-catalog-tools">
            <div className="daily-catalog-search">
              <label htmlFor="daily-catalog-search">Tìm món</label>
              <div className="daily-search-input">
                <Icon icon={faMagnifyingGlass} aria-hidden="true" />
                <input
                  id="daily-catalog-search"
                  type="search"
                  value={search}
                  placeholder="Tên món hoặc mô tả"
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="daily-category-control">
            <span className="daily-category-label">Danh mục hàng</span>
            <div
              className="daily-category-filter"
              role="group"
              aria-label="Lọc món theo danh mục"
            >
              <button
                type="button"
                className={category === "ALL" ? "active" : ""}
                aria-pressed={category === "ALL"}
                onClick={() => setCategory("ALL")}
              >
                Mọi danh mục ({offers.length})
              </button>
              {categories.map((name) => (
                <button
                  type="button"
                  key={name}
                  className={category === name ? "active" : ""}
                  aria-pressed={category === name}
                  onClick={() => setCategory(name)}
                >
                  {`${name} (${offers.filter((o: Row) => String(o.category_name ?? "").trim() === name).length})`}
                </button>
              ))}
            </div>
            </div>
            {(search || category !== "ALL") && (
              <button
                className="ghost small daily-filter-reset"
                onClick={() => {
                  setSearch("");
                  setCategory("ALL");
                }}
              >
                Xóa lọc
              </button>
            )}
          </div>
          <p className="muted daily-filter-count" role="status">Hiển thị {filteredOffers.length} / {offers.length} mặt hàng{category !== "ALL" ? ` · ${category}` : ""}</p>
          {!filteredOffers.length ? (
            <Empty title={offers.length ? "Không tìm thấy món phù hợp" : "Hiện chưa có món đang mở bán"}>
              {offers.length ? "Thử từ khóa hoặc danh mục khác." : "Xem mặt hàng sắp mở bán và theo dõi để nhận thông báo khi có đợt mới."}
            </Empty>
          ) : (
            <div className="daily-rounds">
              {Array.from(new Set<string>(filteredOffers.map((offer: Row) => String(offer.menu_id)))).map((menuId) => {
                const roundOffers = filteredOffers.filter((offer: Row) => String(offer.menu_id) === menuId);
                const post = feed?.posts?.find((entry: Row) => entry.id === menuId);
                const first = roundOffers[0];
                return <section className="daily-round" key={menuId}>
                  <div className="daily-round-heading">
                    <div><span className="round-post-label">Sản phẩm thuộc bài đăng</span><h2>{post?.post_title || `Đợt bán ${menuId.slice(-6).toUpperCase()}`}</h2>
                      <p className="muted">{date(first.opens_at)} → {date(first.closes_at)}</p></div>
                    <span className="muted">{roundOffers.length} sản phẩm</span>
                  </div>
                  {post?.pickup_points?.length > 0 && <div className="daily-round-pickup">
                    <strong>Điểm nhận tập trung miễn phí của bài đăng</strong>
                    <span>{post.pickup_points.map((point: Row) => point.name).join(" · ")}</span>
                    <small>{date(post.pickup_points[0].starts_at)} – {date(post.pickup_points[0].ends_at)}</small>
                  </div>}
                  <div className="daily-products">
              {roundOffers.map((o: Row) => (
                <article
                  key={o.id}
                  className="daily-product"
                  data-offer-id={o.id}
                >
                  <ProductImageGallery images={o.images ?? []} name={o.name} />
                  <div className="daily-product-info">
                    <span className="daily-post-label">{post?.post_title || `Đợt bán ${menuId.slice(-6).toUpperCase()}`}</span>
                    <h2>{o.name}</h2>
                    <details className="offer-round-details"><summary>Thông tin đợt bán</summary><small className="offer-round-label">Đợt {String(o.menu_id).slice(-6).toUpperCase()} · {date(o.opens_at)} → {date(o.closes_at)}</small></details>
                    <p className="muted">{o.description}</p>
                    <ProductReviews productId={o.product_id} request={api} />
                    <p className="stock-note">
                      Số lượng còn lại: <strong>{qty(o.available_qty)} {o.unit}</strong>
                    </p>
                  </div>
                  <div className="daily-product-buy">
                    <div className="food-product-price">
                      {Number(o.list_price) > Number(o.unit_price) && <span><del>{money(o.list_price)}</del> {o.discount_percent > 0 && <small>−{o.discount_percent}%</small>}</span>}
                      <strong>{money(o.unit_price)} / {o.unit}</strong>
                    </div>
                    <button
                      className="primary"
                      disabled={!online || milli(o.available_qty) <= BigInt(0)}
                      onClick={() => add(o)}
                    >
                      {milli(o.available_qty) <= BigInt(0)
                        ? "Hết hàng"
                        : "Thêm vào giỏ"}
                    </button>
                    <button
                      className="ghost small"
                      disabled={!online}
                      onClick={async () => {
                        try {
                          await mutate(
                            "/subscriptions/products/" + o.product_id,
                            {},
                            o.subscribed ? "DELETE" : "POST",
                          );
                        } catch {}
                      }}
                    >
                      {o.subscribed ? "Đang theo dõi" : "Báo khi mở bán"}
                    </button>
                  </div>
                </article>
              ))}
                  </div>
                </section>;
              })}
            </div>
          )}
          </>}
        </>
      )}
    </section>
      {view && (
        <div
          className={mode === "checkout" ? "checkout-inline" : "cart-drawer" + (wideScreen ? " cart-drawer-docked" : "")}
        >
          <Modal
            inline={mode === "checkout"}
            docked={mode === "catalog" && wideScreen}
            title={
              mode === "checkout"
                ? view === "cart"
                  ? "Giỏ hàng"
                  : "Thông tin nhận hàng"
                : view === "cart"
                  ? "Giỏ hàng"
                  : "Xác nhận đặt hàng"
            }
            close={() => {
              setView(null);
              if (mode === "checkout") goTo("catalog");
            }}
          >
            {!cart.length ? (
              <Empty title="Giỏ hàng chưa có món" />
            ) : (
              <>
                <div className="checkout-order-summary">
                  {cart.map((c) => {
                    const inputValue =
                      quantityDrafts[c.id] ?? quantityInputValue(c.quantity);
                    const inputError = quantityError(c, inputValue);
                    return (
                      <div className="cart-line" key={c.id}>
                        <div className="cart-line-main">
                          {c.images?.[0] ? (
                            <img
                              className="cart-product-thumb"
                              src={productImageSrc(c.images[0])}
                              alt=""
                              loading="lazy"
                            />
                          ) : (
                            <div className="cart-product-thumb cart-product-placeholder" aria-hidden="true">
                              <Icon icon={faImage} />
                            </div>
                          )}
                          <div>
                            <strong>{c.name}</strong>
                            <p className="muted">
                              {money(c.unit_price)} / {c.unit}
                            </p>
                            <div className="quantity-controls">
                              <button
                                aria-label={"Giảm " + c.name}
                                onClick={() => adjust(c, -milli(c.quantity_step))}
                              >
                                −
                              </button>
                              <div className="quantity-entry">
                                <div className="quantity-field">
                                  <input
                                    className="cart-quantity-input"
                                    type="text"
                                    inputMode="decimal"
                                    aria-label={`Số lượng ${c.name} (${c.unit})`}
                                    aria-invalid={!!inputError}
                                    aria-describedby={
                                      inputError ? `quantity-error-${c.id}` : undefined
                                    }
                                    value={inputValue}
                                    onChange={(e) => changeQuantityInput(c, e.target.value)}
                                    onBlur={() => finishQuantityInput(c)}
                                    autoComplete="off"
                                  />
                                  <span className="quantity-unit">{c.unit}</span>
                                </div>
                                {inputError && (
                                  <small
                                    id={`quantity-error-${c.id}`}
                                    className="quantity-error"
                                    role="alert"
                                  >
                                    {inputError}
                                  </small>
                                )}
                              </div>
                              <button
                                aria-label={"Tăng " + c.name}
                                onClick={() => adjust(c, milli(c.quantity_step))}
                              >
                                +
                              </button>
                              <button
                                className="ghost"
                                aria-label={"Xóa " + c.name}
                                onClick={() => {
                                  clearQuantityDraft(c.id);
                                  setCart((old) => old.filter((x) => x.id !== c.id));
                                }}
                              >
                                Xóa
                              </button>
                            </div>
                          </div>
                        </div>
                        <strong>
                          {money(lineMoney(c.unit_price, c.quantity))}
                        </strong>
                      </div>
                    );
                  })}
                  {stale && (
                    <div className="notice warn">
                      Giá hoặc lượng còn đã đổi.{" "}
                      <button
                        onClick={() => {
                          setQuantityDrafts({});
                          setCart((old) =>
                            old
                              .map((c) => {
                                const o = offers?.find(
                                  (x: Row) => x.id === c.id,
                                );
                                return o
                                  ? {
                                      ...o,
                                      quantity:
                                        milli(c.quantity) >
                                        milli(o.available_qty)
                                          ? o.available_qty
                                          : c.quantity,
                                    }
                                  : null;
                              })
                              .filter(
                                (c): c is Row =>
                                  !!c && milli(c.quantity) > BigInt(0),
                              ),
                          );
                          setConfirmed(false);
                        }}
                      >
                        Cập nhật giỏ hàng
                      </button>
                    </div>
                  )}
                  <div className="summary-line">
                    <span>Tiền hàng</span>
                    <strong>{money(subtotal)}</strong>
                  </div>
                </div>
                {view === "cart" ? (
                  <div className="actions">
                    <button
                      onClick={() => {
                        setView(null);
                        if (mode === "checkout") goTo("catalog");
                      }}
                    >
                      Mua tiếp
                    </button>
                    <button
                      className="primary"
                      disabled={stale || invalidQuantity || !online}
                      onClick={() => {
                        setView("checkout");
                        goTo("checkout");
                      }}
                    >
                      Tiếp tục đặt hàng
                    </button>
                  </div>
                ) : (
                  <div className="form">
                    <Field label="Cách nhận hàng">
                      <select value={deliveryMethod} onChange={e => setDeliveryMethod(e.target.value)}>
                        <option value="INDIVIDUAL">Giao riêng · Tính phí theo km</option>
                        {(slots.length > 0 || deliveryMethod === "COLLECTIVE") && <option value="COLLECTIVE" disabled={!slots.length}>Nhận tập trung · Miễn phí</option>}
                      </select>
                    </Field>
                    {deliveryMethod === "COLLECTIVE" ? (
                      <>
                      <Field label="Điểm nhận tập trung">
                        <select value={slot?.id ?? ""} onChange={e => setSlotId(e.target.value)}>
                          {!slots.length && <option value="">Chưa có điểm nhận cho giỏ hàng này</option>}
                          {slots.map(s => <option key={s.id} value={s.id}>{s.name} · {s.address_line}</option>)}
                        </select>
                      </Field>
                      {slot && <small>Nhận từ 17:00–18:00 ngày {new Date(slot.starts_at).toLocaleDateString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}</small>}
                      </>
                    ) : (
                      <>
                        <Field label="Địa chỉ nhận">
                          <select value={chosenAddress?.id ?? ""} onChange={e => setAddress(e.target.value)}>
                            {!addresses?.length && <option value="">Chưa có địa chỉ</option>}
                            {addresses?.map((a: Row) => <option key={a.id} value={a.id}>{a.recipient_name} · {a.address_line}</option>)}
                          </select>
                        </Field>
                        <button className="ghost" onClick={() => goTo("profile")}>Quản lý địa chỉ / xác nhận vị trí</button>
                            {delivery && !policy && (
                              <p className="notice warn">Nhóm khách của bạn chưa có chính sách giao riêng.</p>
                            )}
                            {delivery?.warehouse && !delivery.warehouse.configured && (
                              <p className="notice warn">Người bán chưa xác nhận vị trí kho để tính quãng đường.</p>
                            )}
                            {policy?.pricing_mode === "TIERED_KM" && !!policy.distance_enabled && (
                              <p className="muted">
                                {money(policy.per_km_fee)}/km trong {qty(policy.included_km)} km đầu;
                                phần vượt {money(policy.extra_km_fee)}/km.
                                {policy.max_distance_km != null && <> Giao tối đa {qty(policy.max_distance_km)} km.</>}
                                {Number(policy.fee_rounding_step) > 1 && <> Tổng phí làm tròn lên bội số {money(policy.fee_rounding_step)}.</>}
                              </p>
                            )}
                            {policy && !policy.distance_enabled && (
                              <p className="notice warn">Người bán chưa bật chính sách phí giao theo khoảng cách cho nhóm của bạn.</p>
                            )}
                            {!chosenAddress?.latitude && (
                              <p className="notice warn">
                                Địa chỉ này chưa xác nhận vị trí trên bản đồ.
                              </p>
                            )}
                            <button
                              disabled={
                                !online ||
                                busy ||
                                stale ||
                                !chosenAddress?.latitude
                               || !policy?.distance_enabled || delivery?.warehouse?.configured === false}
                              onClick={async () => {
                                setBusy(true);
                                setConfirmed(false);
                                try {
                                  const fresh = await api(
                                    "/delivery/quote",
                                    "POST",
                                    {
                                      addressId: chosenAddress.id,
                                      items: items(),
                                    },
                                  );
                                  setPreviousFee(quote?.shippingFee ?? null);
                                  setQuote({ ...fresh, fingerprint });
                                  setNowMs(Date.now());
                                } catch (e) {
                                  notify((e as Error).message, true);
                                } finally {
                                  setBusy(false);
                                }
                              }}
                            >
                              {busy
                                ? "Đang tính…"
                                : "Tính khoảng cách và phí giao"}
                            </button>
                            {quoteStale && (
                              <p className="notice warn">
                                Địa chỉ, giỏ hoặc chính sách giao đã đổi; hãy
                                tính phí mới và xác nhận lại.
                              </p>
                            )}
                            {previousFee !== null &&
                              quote &&
                              previousFee !== quote.shippingFee && (
                                <p className="notice warn">
                                  Phí giao đổi từ {money(previousFee)} sang{" "}
                                  {money(quote.shippingFee)}.
                                </p>
                              )}
                            {quote && (
                              <div className="notice">
                                <p>Từ {quote.warehouseAddress}</p>
                                <p>
                                  <strong>
                                    {(
                                      quote.distanceMeters / 1000
                                    ).toLocaleString("vi-VN", {
                                      maximumFractionDigits: 2,
                                    })}{" "}
                                    km đường đi
                                  </strong>{" "}
                                  · khoảng{" "}
                                  {Math.ceil(quote.durationSeconds / 60)} phút
                                  di chuyển
                                </p>
                                <p className="muted">
                                  Tuyến đường tham khảo theo mô hình {quote.routeProfile === "motorcycle" ? "xe máy" : "ô tô"}; thực tế có thể khác.
                                </p>
                                <p>
                                  Phí giao:{" "}
                                  <strong>{money(quote.shippingFee)}</strong>
                                </p>
                                <p className="muted">
                                  {expired
                                    ? "Báo phí đã hết hạn. Hãy tính lại."
                                    : "Báo phí có hiệu lực đến " +
                                      date(quote.expiresAt)}
                                </p>
                              </div>
                            )}
                      </>
                    )}
                    <Field label="Thanh toán">
                      <select value={paymentMethod} onChange={e=>setPaymentMethod(e.target.value)}>
                        <option value="COD">COD · Thu đủ khi nhận hàng</option>
                        <option value="PAYOS" disabled={!checkoutConfig?.payosAvailable}>payOS VietQR · Trả đủ sau khi shop duyệt{!checkoutConfig?.payosAvailable ? " (chưa cấu hình)" : ""}</option>
                      </select>
                    </Field>
                    {paymentMethod === "PAYOS" && <p className="notice" role="status">Sau khi đặt hàng, người bán cần duyệt đơn. Khi đơn được duyệt, vào mục Đơn của tôi và chọn “Quét QR thanh toán”.</p>}
                    <Field label="Ghi chú giao hàng">
                      <textarea
                        value={note}
                        maxLength={1000}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </Field>
                    <div className="summary-line">
                      <span>Phí giao</span>
                      <strong>
                        {fee === undefined ? "Chưa tính" : money(fee)}
                      </strong>
                    </div>
                    <div className="summary-line">
                      <strong>VAT</strong><strong>{checkoutConfig ? money(vatAmount) : "Đang tải…"}</strong>
                    </div>
                    <div className="summary-line">
                      <strong>Tổng thanh toán</strong>
                      <strong>
                        {fee === undefined
                          ? "Chưa tính"
                          : money(subtotal + vatAmount + BigInt(String(fee)))}
                      </strong>
                    </div>
                    {deliveryMethod === "INDIVIDUAL" && policy &&
                      subtotal < BigInt(String(policy.minimum_subtotal)) && (
                        <p className="notice warn">
                          Tiền hàng tối thiểu cho cách giao này:{" "}
                          {money(policy.minimum_subtotal)}.
                        </p>
                      )}
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(e) => setConfirmed(e.target.checked)}
                      />
                      Tôi đã kiểm tra món, địa chỉ, VAT, phí giao và cách thanh toán.
                    </label>
                    {!confirmed && <p className="muted" role="status">Vui lòng tích xác nhận phía trên để đặt hàng. Khi thay đổi cách thanh toán, bạn cần xác nhận lại.</p>}
                    <div className="actions">
                      <button
                        onClick={() => {
                          setView("cart");
                          goTo("catalog");
                        }}
                      >
                        Quay lại giỏ
                      </button>
                      <button
                        className="primary"
                        disabled={
                          !online ||
                          busy ||
                          stale ||
                          invalidQuantity ||
                          !checkoutConfig ||
                          !confirmed ||
                          (deliveryMethod === "INDIVIDUAL" &&
                            (!chosenAddress || !policy || subtotal < BigInt(String(policy?.minimum_subtotal ?? 0)) ||
                              !quote || expired || quoteStale)) ||
                          (deliveryMethod === "COLLECTIVE" && !slot)
                        }
                        onClick={submit}
                      >
                        Đặt hàng · Chờ duyệt
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </Modal>
        </div>
      )}
    </>
  );
}

function MenuPostSocial({ menu, state }: { menu: Row; state: string }) {
  const [open, setOpen] = useState(false);
  const {session, online, refresh, mutate} = useApp();
  const social = menu.social;
  if (!social) return <p className="muted menu-social-unavailable">Không thể xem tương tác của đợt lịch sử này.</p>;
  const props = {user:session.user,online,refresh,mutate,request:api,navigate:() => {}};
  const readOnly = !['OPEN','SOLD_OUT'].includes(state);
  return <section className="menu-social" aria-label="Tương tác bài đăng">
    <PostReactions postId={menu.id} readOnly={readOnly} summary={{counts:social.reactions, mine:social.myReaction}} {...props} />
    <button type="button" className="menu-social-toggle" aria-expanded={open} aria-controls={"comments-" + menu.id} onClick={() => setOpen(value => !value)}>
      {open ? "Ẩn bình luận" : "Xem và viết bình luận"} · {social.commentCount}
    </button>
    {open && <div id={"comments-" + menu.id}><PostComments postId={menu.id} readOnly={readOnly} {...props} /></div>}
  </section>;
}

function MenuStock({ menu, products, state }: { menu: Row; products: Row[]; state: string }) {
  const { data, loading } = useData("/admin/menus/" + menu.id);
  const { online } = useApp();
  return <section className="menu-stock" aria-label="Tồn kho và trạng thái sản phẩm">
    <div className="menu-stock-heading">
      <strong>Sản phẩm trong đợt {menu.sale_date}</strong>
      <span className="muted">{loading ? "Đang cập nhật…" : `${data?.items?.length ?? 0} sản phẩm`}</span>
    </div>
    <p className="muted">Lượng còn thuộc riêng đợt này. Đơn chờ duyệt chưa giữ hàng; tồn được trừ khi duyệt và hoàn khi chấp nhận hủy.</p>
    {!online && <p role="status">Mất kết nối. Số lượng dưới đây là dữ liệu đã nhận gần nhất.</p>}
    {!data ? <p role="status">{loading ? "Đang tải sản phẩm…" : "Chưa tải được dữ liệu. Đóng và mở lại để thử lại."}</p> : data.items.length === 0 ? <Empty title="Đợt chưa có sản phẩm" /> :
      <div className="table-scroll"><table className="menu-stock-table">
        <thead><tr><th>Sản phẩm</th><th>Lượng còn</th><th>Chờ duyệt</th><th>Trạng thái bán</th></tr></thead>
        <tbody>{data.items.map((item: Row) => {
          const product = products.find((p: Row) => p.id === item.product_id);
          const inactive = product && (!product.active || product.deleted_at);
          const itemState = !["OPEN", "SOLD_OUT", "SCHEDULED"].includes(state) ? state : inactive ? "INACTIVE" : item.status !== "OPEN" ? "PAUSED" : state === "OPEN" || state === "SOLD_OUT"
            ? Number(item.available_qty) > 0 ? "OPEN" : "SOLD_OUT" : state;
          const label = itemState === "INACTIVE" ? "Ngừng sử dụng" : itemState === "PAUSED" ? "Tạm ngừng bán" : itemState === "OPEN" ? "Đang mở bán" : statuses[itemState] ?? itemState;
          return <tr key={item.id}>
            <td><div className="menu-stock-product">
              <span className="menu-stock-image">
                <Icon icon={faImage} aria-hidden="true" />
                {item.images?.[0] && <img src={productImageSrc(item.images[0])} alt={item.name} loading="lazy" onError={(e) => { e.currentTarget.hidden = true; }} />}
              </span>
              <div><strong>{item.name}</strong><div className="muted">{item.sku}</div></div>
            </div></td>
            <td><strong className={Number(item.available_qty) <= 0 ? "menu-stock-empty" : ""}>{qty(item.available_qty)} {item.unit}</strong></td>
            <td>{qty(item.pending_qty)} {item.unit}</td>
            <td><span className={"status " + itemState}>{label}</span></td>
          </tr>;
        })}</tbody>
      </table></div>}
  </section>;
}

const menuProductPageSize = 12;

function DailyMenus() {
  const { session, mutate, online, notify } = useApp();
  const adminView = session.user.role === "ADMIN";
  const scope = "";
  const { data: inventory } = useData("/admin/stock");
  const { data: pickupPoints } = useData("/admin/config/pickup-slots");
  const { data: menus } = useData("/admin/menus" + scope),
    { data: products } = useData("/admin/products" + scope),
    { data: categories } = useData("/admin/config/categories"),
    { data: units } = useData("/admin/config/units"),
    { data: groups } = useData("/admin/config/groups"),
    { data: priceRules } = useData("/admin/pricing-rules");
  const [form, setForm] = useState<Row | null>(null),
    [stockMenuId, setStockMenuId] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [uploadingPostImage, setUploadingPostImage] = useState(false),
    [copying, setCopying] = useState<Row | null>(null),
    [targetDay, setTargetDay] = useState(
      vnDay(new Date(Date.now() + 86400000)),
    ),
    [productSearch, setProductSearch] = useState(""),
    [productCategory, setProductCategory] = useState("all"),
    [selectedOnly, setSelectedOnly] = useState(false),
    [expandedProductId, setExpandedProductId] = useState<string | null>(null),
    [shownProductCount, setShownProductCount] = useState(menuProductPageSize),
    [roundFilter, setRoundFilter] = useState("all");
  const [discountDrafts, setDiscountDrafts] = useState<Record<string, string>>({});
  const editorRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (form) editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [!!form, form?.id]);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const effectiveStatus = (m: Row) => {
    if (m.status !== "OPEN") return m.status;
    if (clock >= new Date(m.closes_at).getTime()) return "EXPIRED";
    return clock < new Date(m.opens_at).getTime() ? "SCHEDULED" : m.sold_out ? "SOLD_OUT" : "OPEN";
  };
  const edit = async (m?: Row) => {
    if (busy || uploadingPostImage) return;
    setDiscountDrafts({});
    if (!priceRules) {
      notify("Đang tải quy tắc giá, vui lòng thử lại sau một lát", true);
      return;
    }
    setProductSearch("");
    setProductCategory("all");
    setSelectedOnly(false);
    setExpandedProductId(null);
    setShownProductCount(menuProductPageSize);
    if (!m) {
      setForm({
        pickupSlotIds: [],
        postImages: [],
        postImageInput: "",
        saleDate: vnDay(),
        closeDate: "",
        closeTime: "",
        allowedGroupIds: null,
        audienceMode: "MENU",
        items: [],
      });
      return;
    }
    setBusy(true);
    try {
      const full = await api("/admin/menus/" + m.id);
      const closeMoment = new Date(full.closes_at);
      const localCloseTime = closeMoment.toLocaleTimeString("en-GB", {
        timeZone: "Asia/Ho_Chi_Minh",
        hourCycle: "h23",
        hour: "2-digit",
        minute: "2-digit",
      });
      const calendarCloseDay = vnDay(closeMoment);
      const inclusiveCloseDay =
        localCloseTime === "00:00"
          ? vnDateOffset(calendarCloseDay, -1)
          : calendarCloseDay;
      const existingItems = full.items.map((o: Row) => ({
          productId: o.product_id,
          availableQty: o.available_qty,
          listPrice: o.list_price ?? "",
          allowedGroupIds:
            products?.find((p: Row) => p.id === o.product_id)
              ?.allowed_group_ids == null
              ? (full.audience_mode === "PRODUCT" ? o.allowed_group_ids : null)
              : null,
          enabled: o.status === "OPEN",
          expectedVersion: o.version,
          prices: o.prices.map((price: Row) => ({groupId:price.group_id,unitPrice:price.unit_price})),
        }));
      setForm({
        ...full,
        postTitle: full.post_title ?? "",
        postBody: full.post_body ?? "",
        postImages: full.post_images ?? [],
        postImageInput: "",
        receivingNote: full.receiving_note ?? "",
        pickupSlotIds: full.pickup_slot_ids ?? [],
        audienceMode: full.audience_mode ?? "MENU",
        saleDate: full.sale_date,
        closeDate:
          inclusiveCloseDay === full.sale_date ? "" : inclusiveCloseDay,
        closeTime: localCloseTime === "00:00" ? "" : localCloseTime,
        allowedGroupIds: full.allowed_group_ids,
        existingItems,
        items: existingItems.filter((item: Row) => item.enabled),
      });
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const uploadPostImages = async (files: File[]) => {
    if (!form || files.length + (form.postImages?.length ?? 0) > 5) {
      notify("Bài đăng được chọn tối đa 5 ảnh", true);
      return;
    }
    setUploadingPostImage(true);
    try {
      for (const file of files) {
        const asset = await uploadImage(file, "MENU_POST");
        setForm(current => current && { ...current, postImages: [...(current.postImages ?? []), {assetId: asset.id}] });
      }
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setUploadingPostImage(false);
    }
  };
  const save = async (status: string) => {
    if (!form || uploadingPostImage) return;
    if (status === "OPEN" && (!inventory || stockErrors.size)) return;
    if (!priceRules) {
      notify("Chưa tải được quy tắc giá; chưa lưu menu", true);
      return;
    }
    setBusy(true);
    try {
      const closeDay = form.closeDate || form.saleDate;
      const closesAt = form.closeTime
        ? `${closeDay}T${form.closeTime}:00+07:00`
        : `${vnDateOffset(closeDay, 1)}T00:00:00+07:00`;
      const { existingItems, postImageInput, post_image_url, post_image_asset_id, post_images, ...menuForm } = form;
      menuForm.items = form.items.map((item: Row) => ({ ...item,
        prices: item.prices.filter((price: Row) => price.unitPrice !== ""),
      }));
      await mutate(
        "/admin/menus" + (form.id ? "/" + form.id : ""),
        { ...menuForm, closesAt, status, expectedVersion: form.version },
        form.id ? "PATCH" : "POST",
      );
      setForm(null);
      notify("Đã lưu menu");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  const changeStatus = async (m: Row, status: string) => {
    setBusy(true);
    try {
      await mutate(
        "/admin/menus/" + m.id,
        { expectedVersion: m.version, status },
        "PATCH",
      );
      notify("Đã cập nhật menu");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  const changeItem = (id: string, values: Row) =>
    setForm((f) =>
      f
        ? {
            ...f,
            items: f.items.map((i: Row) =>
              i.productId === id ? { ...i, ...values } : i,
            ),
          }
        : f,
    );
  const toggleMenuItem = (product: Row, checked: boolean) => {
    setExpandedProductId(current => checked ? product.id : current === product.id ? null : current);
    setForm((f) => {
      if (!f) return f;
      const cached = (f.existingItems ?? []).find((i: Row) => i.productId === product.id);
      if (checked) {
        const level = inventory?.find((row: Row) => row.id === product.id);
        const prices = menuPrices(level?.average_cost ?? "", groups ?? [], priceRules);
        const highest = prices.reduce((max, price) => Math.max(max, Number(price.unitPrice)), 0);
        const item = cached ?? {
          productId: product.id, availableQty: "0",
          listPrice: Math.max(Number(product.list_price ?? 0), highest) || "",
          allowedGroupIds: null, prices,
        };
        return { ...f, items: [...f.items, { ...item, enabled: true,
          allowedGroupIds: f.audienceMode === "PRODUCT" ? item.allowedGroupIds : null }] };
      }
      const removed = f.items.find((i: Row) => i.productId === product.id);
      return { ...f,
        items: f.items.filter((i: Row) => i.productId !== product.id),
        existingItems: [...(f.existingItems ?? []).filter((i: Row) => i.productId !== product.id), removed].filter(Boolean),
      };
    });
  };
  const setMenuAudience = (mode: "MENU" | "PRODUCT", allowedGroupIds: string[] | null) => {
    setForm((f) => f ? {
      ...f, audienceMode: mode, allowedGroupIds,
      items: f.items.map((item: Row) => ({ ...item, allowedGroupIds: mode === "MENU" ? null : item.allowedGroupIds })),
      existingItems: (f.existingItems ?? []).map((item: Row) => ({ ...item, allowedGroupIds: mode === "MENU" ? null : item.allowedGroupIds })),
    } : f);
  };
  const menuGroupNames = form?.allowedGroupIds == null ? "Tất cả nhóm" : form.allowedGroupIds
    .map((id: string) => groups?.find((g: Row) => g.id === id)?.name ?? "Nhóm đã ngừng dùng").join(", ");
  const selectedProducts = new Map<string, Row>((form?.items ?? []).map((item: Row) => [item.productId, item]));
  const stockByProduct = new Map<string, Row>((inventory ?? []).map((row: Row) => [row.id, row]));
  const stockErrors = new Map<string, string>();
  if (inventory) {
    for (const [id, item] of selectedProducts) {
      const level = stockByProduct.get(id);
      const available = level?.quantity ?? 0;
      if (item.enabled && Number(item.availableQty) > Number(available)) {
        const productName = level?.name ?? products?.find((product: Row) => product.id === id)?.name ?? "Sản phẩm";
        stockErrors.set(id, `${productName}: chỉ còn ${qty(available)} ${level?.unit ?? "đơn vị"} trong kho.`);
      }
    }
  }
  const searchText = productSearch.trim().toLocaleLowerCase("vi-VN");
  const filteredProducts = (products ?? []).filter((p: Row) => {
    if (!p.active || p.deleted_at) return false;
    if (selectedOnly) return selectedProducts.has(p.id);
    const matchesCategory = productCategory === "all" || p.category_id === productCategory;
    const matchesSearch = `${p.name} ${p.sku}`.toLocaleLowerCase("vi-VN").includes(searchText);
    return matchesCategory && matchesSearch;
  });
  const showSelectedProducts = (show: boolean) => {
    if (show === selectedOnly) return;
    setSelectedOnly(show);
    setShownProductCount(menuProductPageSize);
  };
  const roundGroups = [
    { id: "all", label: "Tất cả", states: [] },
    { id: "live", label: "Đang diễn ra", states: ["OPEN", "SOLD_OUT"] },
    { id: "scheduled", label: "Sắp mở", states: ["SCHEDULED"] },
    { id: "draft", label: "Bản nháp", states: ["DRAFT"] },
    { id: "ended", label: "Đã kết thúc", states: ["CLOSED", "EXPIRED"] },
  ];
  const visibleMenus = (menus ?? []).filter((menu: Row) =>
    (roundFilter === "all" || roundGroups.find((group) => group.id === roundFilter)?.states.includes(effectiveStatus(menu))),
  );
  return (
    <>
      <Heading
        title="Menu theo ngày"
        sub="Lên lịch bán, chọn món và theo dõi tồn kho theo từng đợt."
      >
        <button
          className="primary"
          disabled={!online || busy || uploadingPostImage || !products || !categories || !groups || !priceRules || !inventory || !pickupPoints}
          onClick={() => edit()}
        >
          Tạo menu ngày
        </button>
      </Heading>
      {form && (
        <section className="panel menu-editor" ref={editorRef} aria-label={form.id ? "Sửa menu" : "Tạo menu"}>
          <div className="panel-head menu-editor-head">
            <div><h2>{form.id ? "Sửa menu" : "Tạo menu"}</h2><p className="muted">{form.saleDate} · {form.id ? "Cập nhật đợt bán" : "Đợt bán mới"}</p></div>
            <button disabled={busy || uploadingPostImage} onClick={() => setForm(null)}>Đóng biểu mẫu</button>
          </div>
          <div className="form">
            <div className="menu-editor-layout">
            <section className="menu-products-area" aria-label="Chọn sản phẩm mở bán">
              <div className="menu-products-heading">
                <h3>Sản phẩm mở bán</h3>
              </div>
              <div className="menu-product-toolbar" role="group" aria-label="Danh sách sản phẩm">
                <button type="button" aria-pressed={!selectedOnly} onClick={() => showSelectedProducts(false)}>Danh mục</button>
                <button type="button" aria-pressed={selectedOnly} onClick={() => showSelectedProducts(true)}>Đã chọn ({form.items.length})</button>
              </div>
            {!selectedOnly && <div className="form-grid menu-product-filters">
              <Field label="Lọc theo danh mục">
                <select
                  value={productCategory}
                  onChange={(e) => {
                    setProductCategory(e.target.value);
                    setShownProductCount(menuProductPageSize);
                  }}
                >
                  <option value="all">Tất cả danh mục</option>
                  {categories
                    ?.filter((category: Row) => category.active)
                    .map((category: Row) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Tìm theo tên hoặc SKU">
                <input
                  value={productSearch}
                  onChange={(e) => {
                    setProductSearch(e.target.value);
                    setShownProductCount(menuProductPageSize);
                  }}
                  placeholder="Ví dụ: rau muống hoặc SKU-000009"
                />
              </Field>
            </div>}
            <div className="menu-product-list">
              {filteredProducts.slice(0, shownProductCount).map((p: Row) => {
                  const item = selectedProducts.get(p.id);
                  const stock = stockByProduct.get(p.id);
                  const stockQuantity = stock?.quantity ?? 0;
                  const unit = stock?.unit ?? units?.find((u: Row) => u.id === p.unit_id)?.label ?? "đơn vị";
                  const expanded = !!item && expandedProductId === p.id;
                  const settingsId = "menu-product-settings-" + p.id;
                  const stockError = stockErrors.get(p.id);
                  const stockErrorId = settingsId + "-stock-error";
                  return (
                    <article key={p.id} className={"menu-product" + (item ? " selected" : "") + (expanded ? " expanded" : "")} data-product-id={p.id}>
                      <div className="menu-product-summary">
                        <span className="menu-stock-image" aria-hidden="true">
                          <Icon icon={faImage} />
                          {!!p.images?.length && <img src={productImageSrc(p.images[0])} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                        </span>
                        <div className="menu-pick-title">
                          <strong>{p.name}</strong>
                          <small>{p.sku} · {unit}</small>
                          <small className={Number(stockQuantity) <= 0 ? "menu-stock-empty" : "menu-card-stock"}>
                            {Number(stockQuantity) > 0 ? `Tồn kho ${qty(stockQuantity)} ${unit}` : "Hết hàng trong kho"}
                          </small>
                        </div>
                      </div>
                      <div className="menu-product-actions">
                        {item && (
                          <span className={stockError ? "menu-stock-empty" : "muted"}>
                            {stockError ? "Vượt tồn kho" : Number(item.availableQty) > 0 ? `Bán ${qty(item.availableQty)} ${unit}` : "Chưa nhập lượng bán"}
                          </span>
                        )}
                        <button type="button" disabled={!online || busy} aria-expanded={item ? expanded : undefined}
                          aria-controls={expanded ? settingsId : undefined} onClick={() => {
                            if (item) setExpandedProductId(expanded ? null : p.id);
                            else toggleMenuItem(p, true);
                          }}>{item ? (expanded ? "Thu gọn" : "Chỉnh") : "Chọn"}</button>
                        {item && (
                          <button type="button" className="ghost" disabled={!online || busy}
                            onClick={() => toggleMenuItem(p, false)}>Bỏ chọn</button>
                        )}
                      </div>
                      {expanded && item && (
                        <div className="menu-selected-product" id={settingsId}>
                          <ProductImageGallery images={p.images ?? []} name={p.name} />
                        <div className="menu-line-fields">
                          <p className="muted menu-pricing-note">Giá vốn bình quân {stock?.average_cost == null ? "chưa có" : money(stock.average_cost) + " / " + unit}</p>
                          <Field
                            label={`Lượng còn có thể bán (${unit})`}
                          >
                            <input
                              type="number"
                              min="0"
                              max={inventory ? stockQuantity : undefined}
                              step={p.quantity_step}
                              aria-invalid={!!stockError}
                              aria-describedby={stockError ? stockErrorId : undefined}
                              value={item.availableQty}
                              onChange={(e) =>
                                changeItem(p.id, {
                                  availableQty: e.target.value,
                                })
                              }
                            />
                          </Field>
                          {stockError && <small id={stockErrorId} className="menu-stock-empty">{stockError}</small>}
                          <Field label="Giá niêm yết (đ)">
                            <input type="number" min="0" step="1" value={item.listPrice}
                              onChange={e => {
                                setDiscountDrafts({});
                                changeItem(p.id, {listPrice:e.target.value});
                              }} />
                          </Field>
                          {(groups ?? []).filter((g: Row) => g.active).map((g: Row) => {
                            const sale = String(item.prices.find((price: Row) => price.groupId === g.id)?.unitPrice ?? "");
                            const list = String(item.listPrice ?? "");
                            const valid = /^\d+$/.test(list) && /^\d+$/.test(sale);
                            const listAmount = valid ? BigInt(list) : 0n;
                            const saleAmount = valid ? BigInt(sale) : 0n;
                            const discount = valid && listAmount > 0n && saleAmount <= listAmount
                              ? ((listAmount - saleAmount) * 100n * 2n + listAmount) / (2n * listAmount)
                              : null;
                            const discountKey = p.id + ":" + g.id;
                            return <div key={g.id}>
                              <Field label={"Giá bán · " + g.name}>
                                <input type="number" min="0" step="1" value={sale}
                                  onChange={e => {
                                    setDiscountDrafts(current => {
                                      const next = {...current};
                                      delete next[discountKey];
                                      return next;
                                    });
                                    changeItem(p.id, {prices:[...item.prices.filter((price: Row) => price.groupId !== g.id),
                                      {groupId:g.id,unitPrice:e.target.value}]});
                                  }} />
                              </Field>
                              <Field label={"Giảm (%) · " + g.name}>
                                <input type="number" min="0" max="100" step="1" inputMode="numeric"
                                  disabled={!/^\d+$/.test(list) || BigInt(list) === 0n}
                                  value={discountDrafts[discountKey] ?? discount?.toString() ?? ""}
                                  onChange={e => {
                                    const value = e.target.value;
                                    if (value !== "" && (!/^\d+$/.test(value) || Number(value) > 100)) return;
                                    setDiscountDrafts(current => ({...current, [discountKey]: value}));
                                    if (value === "") return;
                                    const base = BigInt(list);
                                    const price = (base * (100n - BigInt(value)) + 50n) / 100n;
                                    changeItem(p.id, {prices:[...item.prices.filter((entry: Row) => entry.groupId !== g.id),
                                      {groupId:g.id,unitPrice:price.toString()}]});
                                  }} />
                              </Field>
                              <small className="menu-discount">Giá bán được làm tròn đến đồng.</small>
                              {valid && saleAmount > listAmount && <small className="menu-stock-empty">Giá bán vượt giá niêm yết</small>}
                            </div>;
                          })}
                          {form.audienceMode !== "PRODUCT" ? (
                            <p className="muted">Nhóm mua theo menu: {menuGroupNames}.
                              {p.allowed_group_ids != null && <> Sản phẩm vẫn giữ giới hạn nhóm đã cấu hình trong danh mục.</>}
                            </p>
                          ) : p.allowed_group_ids == null ? (
                            <AudienceFields
                              groups={groups ?? []}
                              value={item.allowedGroupIds ?? null}
                              onChange={(allowedGroupIds) =>
                                changeItem(p.id, { allowedGroupIds })
                              }
                              legend="Nhóm được phép mua món này"
                            />
                          ) : (
                            <p className="muted">
                              Nhóm mua được khóa theo sản phẩm: {p.allowed_group_ids
                                .map(
                                  (id: string) =>
                                    groups?.find((g: Row) => g.id === id)?.name ??
                                    "Nhóm đã ngừng dùng",
                                )
                                .join(", ")}
                            </p>
                          )}
                          {form.id && ["OPEN", "SOLD_OUT"].includes(effectiveStatus(form)) && (
                          <label className="check">
                            <input
                              type="checkbox"
                              checked={item.enabled}
                              onChange={(e) =>
                                changeItem(p.id, { enabled: e.target.checked })
                              }
                            />
                            Đang bán món này
                          </label>
                          )}
                        </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              {!filteredProducts.length && (
                <p className="empty">{selectedOnly ? "Chưa có sản phẩm được chọn." : "Không có sản phẩm phù hợp với bộ lọc."}</p>
              )}
            </div>
            {shownProductCount < filteredProducts.length && <button type="button" className="menu-products-more"
              onClick={() => setShownProductCount(count => count + menuProductPageSize)}>
              Xem thêm · {filteredProducts.length - shownProductCount} sản phẩm
            </button>}
            </section>
            <aside className="menu-settings" aria-label="Thiết lập menu">
            <details className="menu-form-disclosure" name="menu-settings-section">
            <summary>Thời gian mở bán</summary>
            <div className="menu-settings-body">
            <div className="form-grid menu-schedule-grid">
              <Field label="Ngày bắt đầu bán">
                <input
                  type="date"
                  value={form.saleDate}
                  disabled={!!form.id}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      saleDate: e.target.value,
                      ...(form.closeDate && form.closeDate < e.target.value
                        ? { closeDate: "" }
                        : {}),
                    })
                  }
                />
              </Field>
              <Field label="Mở lúc (giờ Việt Nam)">
                <input
                  type="time"
                  value={
                    form.opensAt
                      ? new Date(form.opensAt).toLocaleTimeString("en-GB", {
                          timeZone: "Asia/Ho_Chi_Minh",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : form.opens_at
                        ? new Date(form.opens_at).toLocaleTimeString("en-GB", {
                            timeZone: "Asia/Ho_Chi_Minh",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "00:00"
                  }
                  onChange={(e) =>
                    setForm({
                      ...form,
                      opensAt:
                        form.saleDate + "T" + e.target.value + ":00+07:00",
                    })
                  }
                />
              </Field>
              <Field label="Ngày đóng đợt (để trống: hết ngày bán)">
                <input
                  type="date"
                  min={form.saleDate}
                  value={form.closeDate ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, closeDate: e.target.value })
                  }
                />
              </Field>
              <Field label="Giờ đóng (để trống: hết ngày đã chọn)">
                <input
                  type="time"
                  value={form.closeTime ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, closeTime: e.target.value })
                  }
                />
              </Field>
            </div>
            <p className="muted">
              Để trống giờ đóng để bán đến hết ngày đã chọn.
            </p>
            </div>
            </details>
            <details className="menu-form-disclosure" name="menu-settings-section">
            <summary>Chọn các điểm giao</summary>
            <div className="menu-settings-body">
            <fieldset className="audience-fields" aria-label="Điểm nhận tập trung miễn phí">
              {(pickupPoints ?? []).filter((point: Row) => point.active || form.pickupSlotIds.includes(point.id)).map((point: Row) =>
                <label key={point.id} className="check">
                  <input type="checkbox" checked={form.pickupSlotIds.includes(point.id)} onChange={e =>
                    setForm({ ...form, pickupSlotIds: e.target.checked ? [...form.pickupSlotIds, point.id] : form.pickupSlotIds.filter((id: string) => id !== point.id) })} />
                  <span>{point.name}{!point.active && " (đã ngừng dùng)"}</span>
                </label>)}
              {!pickupPoints?.some((point: Row) => point.active) &&
                <p className="muted">Chưa có điểm nhận khả dụng.</p>}
            </fieldset>
            </div>
            </details>
            <details className="menu-form-disclosure" name="menu-settings-section">
            <summary>Nhóm khách hàng</summary>
            <div className="menu-settings-body">
            <fieldset className="audience menu-audience">
              <legend>Nhóm được phép mua trong menu</legend>
              <label className="check">
                <input type="radio" name="menu-audience-mode"
                  checked={form.audienceMode === "MENU" && form.allowedGroupIds == null}
                  onChange={() => setMenuAudience("MENU", null)} />
                Tất cả nhóm
              </label>
              {groups?.filter((g: Row) => g.active).map((g: Row) => (
                <label className="check" key={g.id}>
                  <input type="checkbox"
                    checked={form.audienceMode === "MENU" && !!form.allowedGroupIds?.includes(g.id)}
                    onChange={(e) => {
                      const selected = form.audienceMode === "MENU" ? form.allowedGroupIds ?? [] : [];
                      setMenuAudience("MENU", e.target.checked ? [...selected, g.id] : selected.filter((id: string) => id !== g.id));
                    }} />
                  {g.name}
                </label>
              ))}
              <label className="check">
                <input type="radio" name="menu-audience-mode"
                  checked={form.audienceMode === "PRODUCT"}
                  onChange={() => setMenuAudience("PRODUCT", null)} />
                Tùy chỉnh theo từng sản phẩm
              </label>
            </fieldset>
            </div>
            </details>
            <details className="menu-form-disclosure" name="menu-settings-section">
              <summary>Bài đăng</summary>
              <div className="menu-settings-body form menu-post-editor">
              <div className="post-editor-heading"><div><h3>Soạn bài mở bán</h3><p>Giới thiệu sản phẩm và thông tin nhận hàng tới khách.</p></div><span>{form.items.length} sản phẩm đã chọn</span></div>
              <div className="post-editor-columns"><div className="post-editor-fields">
              <Field label="Tiêu đề bài trên bảng tin"><input placeholder="Ví dụ: Thực phẩm tươi hôm nay" value={form.postTitle ?? ""} maxLength={150} onChange={e=>setForm({...form,postTitle:e.target.value})}/></Field>
              <Field label="Nội dung giới thiệu"><textarea placeholder="Giới thiệu các sản phẩm và thông tin cần lưu ý…" value={form.postBody ?? ""} maxLength={2000} onChange={e=>setForm({...form,postBody:e.target.value})}/></Field>
              <div className="post-upload"><label className="post-upload-label"><span className="post-upload-icon" aria-hidden="true">＋</span><span><strong>Thêm ảnh từ thiết bị</strong><small>{(form.postImages ?? []).length}/5 ảnh · JPEG, PNG, WebP</small></span>
                <input type="file" multiple accept="image/jpeg,image/png,image/webp"
                  disabled={!online || busy || uploadingPostImage}
                  aria-describedby="menu-post-image-hint"
                  onChange={e => {
                    const files = Array.from(e.currentTarget.files ?? []);
                    e.currentTarget.value = "";
                    if (files.length) void uploadPostImages(files);
                  }} />
              </label><small id="menu-post-image-hint" className="muted">Tối đa 5 ảnh, mỗi ảnh 5 MiB. Ảnh đầu tiên là ảnh đại diện.</small></div>
              {uploadingPostImage && <small role="status">Đang tải ảnh…</small>}
              <Field label="Hoặc dán URL ảnh HTTPS">
                <div className="menu-post-url"><input type="url" disabled={uploadingPostImage} value={form.postImageInput ?? ""}
                  placeholder="https://…" onChange={e => setForm({ ...form, postImageInput: e.target.value })} />
                  <button type="button" disabled={busy || uploadingPostImage || !form.postImageInput?.trim()} onClick={() => {
                    const url = form.postImageInput.trim();
                    if ((form.postImages ?? []).length >= 5) return notify("Bài đăng được chọn tối đa 5 ảnh", true);
                    if (!/^https:\/\//i.test(url)) return notify("URL ảnh phải bắt đầu bằng https://", true);
                    if ((form.postImages ?? []).some((image: Row) => image.url === url)) return notify("URL ảnh đã được thêm", true);
                    setForm({ ...form, postImages: [...(form.postImages ?? []), {url}], postImageInput: "" });
                  }}>Thêm ảnh</button></div>
              </Field>
              {(form.postImages ?? []).length > 0 && <div className="menu-post-gallery">{form.postImages.map((image: Row, index: number) =>
                <div className="menu-post-image" key={image.assetId ?? image.url}>
                  <img src={image.assetId ? productImageSrc(image.assetId) : image.url} alt={`Ảnh bài đăng ${index + 1}`} />
                  <div><small>{index === 0 ? "Ảnh đại diện" : `Ảnh ${index + 1}`}</small>
                    <button type="button" className="small" disabled={busy || uploadingPostImage} onClick={() =>
                      setForm({ ...form, postImages: form.postImages.filter((_: Row, i: number) => i !== index) })}>Gỡ</button></div>
                </div>)}</div>}
              <Field label="Hướng dẫn nhận hàng"><textarea value={form.receivingNote ?? ""} maxLength={500} onChange={e=>setForm({...form,receivingNote:e.target.value})}/></Field>
              </div><aside className="post-preview" aria-label="Xem trước bài đăng">
                <div className="post-preview-caption">Xem trước trên bảng tin</div>
                <div className="post-preview-card"><div className="feed-author"><span className="feed-avatar" aria-hidden="true">F</span><div><strong>Cửa hàng</strong><small>Bài đăng mở bán</small></div></div>
                  <h4>{form.postTitle || "Tiêu đề bài đăng"}</h4>
                  <p className={form.postBody ? "" : "muted"}>{form.postBody || "Nội dung giới thiệu sẽ xuất hiện tại đây."}</p>
                  {(form.postImages ?? []).length > 0 ? <div className="post-preview-images">{form.postImages.map((image: Row, index: number) => <img key={image.assetId ?? image.url} src={image.assetId ? productImageSrc(image.assetId) : image.url} alt={`Ảnh xem trước ${index + 1}`} />)}</div> : <div className="post-preview-empty">Ảnh bài đăng sẽ xuất hiện ở đây</div>}
                  <div className="post-preview-products"><strong>Sản phẩm mở bán</strong>{form.items.length ? form.items.slice(0,3).map((item: Row) => <span key={item.productId}>{products?.find((p: Row) => p.id === item.productId)?.name ?? "Sản phẩm"}</span>) : <span>Chọn sản phẩm để hiển thị trong bài.</span>}{form.items.length > 3 && <small>Và {form.items.length - 3} sản phẩm khác</small>}</div>
                  <small>Giá và ưu đãi hiển thị theo nhóm khách hàng.</small>
                </div>
              </aside></div>
              </div>
            </details>
            </aside>
            </div>
            <footer className="menu-save-bar">
              <span>
                <strong>{form.items.length} sản phẩm đã chọn</strong>
                {stockErrors.size > 0 && <small className="menu-stock-empty" aria-live="polite">{stockErrors.values().next().value}</small>}
              </span>
            <div className="actions menu-editor-actions">
              <button disabled={!online || busy || uploadingPostImage || !priceRules} onClick={() => save("DRAFT")}>
                Lưu nháp
              </button>
              <button
                className="primary"
                disabled={!online || busy || uploadingPostImage || !form.items.length || !priceRules || !inventory || stockErrors.size > 0}
                onClick={() => save("OPEN")}
              >
                Lưu và mở bán
              </button>
              {form.id && (
                <button
                  disabled={!online || busy || uploadingPostImage || !priceRules}
                  onClick={() => save("CLOSED")}
                >
                  Lưu và đóng bán
                </button>
              )}
            </div>
            </footer>
          </div>
        </section>
      )}
      <section className="menu-history" aria-label="Lịch sử mở bán">
        <div className="menu-history-heading"><div><h2>Lịch sử mở bán</h2><p className="muted">Theo dõi lịch, trạng thái và lượng hàng từng đợt.</p></div>{menus && <span className="muted">{visibleMenus.length} / {menus.length} đợt</span>}</div>
        <div className="menu-round-filters" role="group" aria-label="Lọc đợt bán theo trạng thái">
          {roundGroups.map((group) => (
            <button key={group.id} type="button" aria-pressed={roundFilter === group.id} onClick={() => setRoundFilter(group.id)}>
              {group.label}{menus ? ` (${group.id === "all" ? menus.length : menus.filter((menu: Row) => group.states.includes(effectiveStatus(menu))).length})` : ""}
            </button>
          ))}
        </div>
        <div className="menu-history-posts">
            {visibleMenus.map((m: Row) => (
              <article className="panel menu-history-post" key={m.id}>
                <header className="menu-history-post-head"><div><span className="menu-history-post-kicker">BÀI MỞ BÁN · {m.sale_date}</span><h3>{m.post_title || `Đợt ${m.sale_date}`}</h3><small>ID {m.id}</small></div><Status value={effectiveStatus(m)} /></header>
                {m.post_body && <ExpandablePostText className="menu-history-post-body" text={m.post_body} />}
                {(m.post_images?.length || m.post_image_asset_id || m.post_image_url) && <div className="menu-history-images">{(m.post_images?.length ? m.post_images : [{assetId:m.post_image_asset_id,url:m.post_image_url}]).map((image: Row, index: number) =>
                  <img key={image.assetId || image.url || index} src={image.assetId ? productImageSrc(image.assetId) : image.url} alt={`Ảnh bài đăng ${index+1}`} loading="lazy" />)}</div>}
                <div className="menu-history-time"><span>Mở <strong>{date(m.opens_at)}</strong></span><span>Đóng <strong>{date(m.closes_at)}</strong></span></div>
                <MenuPostSocial menu={m} state={effectiveStatus(m)} />
                {stockMenuId === m.id && <div className="menu-history-stock" id={"menu-stock-" + m.id}>
                  <MenuStock menu={m} products={products ?? []} state={effectiveStatus(m)} />
                </div>}
                  <div className="actions menu-round-actions">
                    <button aria-expanded={stockMenuId === m.id} aria-controls={"menu-stock-" + m.id}
                      onClick={() => setStockMenuId(stockMenuId === m.id ? null : m.id)}>
                      {stockMenuId === m.id ? "Ẩn tồn / trạng thái" : "Xem tồn / trạng thái"}
                    </button>
                    <button className="primary" disabled={m.legacy_store_menu || !online || busy || uploadingPostImage || !priceRules} onClick={() => edit(m)}>
                      Sửa món / giá / kho
                    </button>
                    {!m.legacy_store_menu && m.status !== "OPEN" && new Date(m.closes_at).getTime() > clock && m.sale_date >= vnDay() && (
                      <button className="primary"
                        disabled={!online || busy}
                        onClick={() => changeStatus(m, "OPEN")}
                      >
                        Mở bán
                      </button>
                    )}
                    {m.status === "OPEN" && effectiveStatus(m) !== "EXPIRED" && (
                      <button className="menu-close-action"
                        disabled={!online || busy}
                        onClick={() => changeStatus(m, "CLOSED")}
                      >
                        Đóng bán
                      </button>
                    )}
                    <button
                      disabled={!online || busy}
                      onClick={() => setCopying(m)}
                    >
                      Sao chép
                    </button>
                  </div>
              </article>
            ))}
        {!menus ? <p className="spinner">Đang tải đợt bán…</p> : !visibleMenus.length && <Empty title={menus.length ? "Không có đợt bán phù hợp" : "Chưa có menu"} />}
      </div>
      </section>
      {copying && (
        <Modal
          title="Sao chép menu sang ngày khác"
          close={() => setCopying(null)}
        >
          <div className="form">
            <input
              aria-label="Ngày menu mới"
              type="date"
              value={targetDay}
              onChange={(e) => setTargetDay(e.target.value)}
            />
            <p>
              Danh sách món và giá được sao chép; lượng bán về 0, menu ở trạng
              thái nháp.
            </p>
            <button
              disabled={!online || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await mutate("/admin/menus/" + copying.id + "/copy", {
                    saleDate: targetDay,
                  });
                  setCopying(null);
                  notify("Đã tạo menu nháp");
                } catch {
                } finally {
                  setBusy(false);
                }
              }}
            >
              Tạo bản sao
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

const overviewPresets = [
  { id: "today", label: "Hôm nay" },
  { id: "week", label: "7 ngày gần nhất" },
  { id: "month", label: "Tháng này" },
] as const;

function Overview() {
  const reportPrefix = "/admin/reports";
  const [range, setRange] = useState(() => {
    const end = vnDay();
    return { start: vnDateOffset(end, -6), end };
  });
  const [draft, setDraft] = useState(range);
  const [preset, setPreset] = useState("week");
  const [details, setDetails] = useState(false);
  const { reload } = useApp();
  const query = new URLSearchParams({ from: range.start, to: range.end });
  const { data: response, loading } = useData(reportPrefix + "/overview?" + query);
  const data: OverviewData | null = response?.from === range.start && response?.to === range.end ? response : null;
  const applyPreset = (id: string) => {
    const end = vnDay();
    const start = id === "today" ? end : id === "month" ? end.slice(0, 7) + "-01" : vnDateOffset(end, -6);
    setPreset(id);
    setDraft({ start, end });
    setRange({ start, end });
  };
  return (
    <>
      <Heading title="Tổng quan" sub="Doanh thu hàng ghi nhận khi giao thành công. VAT và phí giao hiển thị riêng." />
      <div className="overview-controls">
        <div className="overview-presets" role="group" aria-label="Khoảng thời gian thống kê">
          {overviewPresets.map(({ id, label }) => <button key={id} type="button" aria-pressed={preset === id} onClick={() => applyPreset(id)}>{label}</button>)}
        </div>
        <form className="overview-range" onSubmit={(e) => { e.preventDefault(); setPreset("custom"); setRange(draft); }}>
          <Field label="Từ ngày"><input type="date" required value={draft.start} max={draft.end || vnDay()} onChange={(e) => setDraft({ ...draft, start: e.target.value })} /></Field>
          <Field label="Đến ngày"><input type="date" required value={draft.end} min={draft.start} max={vnDay()} onChange={(e) => setDraft({ ...draft, end: e.target.value })} /></Field>
          <button type="submit">Áp dụng</button>
        </form>
      </div>
      {data ? <OverviewDashboard data={data} money={money} statusLabels={statuses} /> : loading ? <p className="spinner" role="status">Đang tải tổng quan…</p> : <div className="notice warn" role="status">Chưa tải được tổng quan. Chọn khoảng tối đa 366 ngày hoặc <button className="small" type="button" onClick={reload}>Tải lại</button>.</div>}
      <details className="panel overview-report-details" onToggle={(e) => setDetails(e.currentTarget.open)}>
        <summary>Báo cáo chi tiết theo ngày và tháng</summary>
        {details && <div className="panel-body"><DailyReports /></div>}
      </details>
    </>
  );
}

function DailyReports() {
  const prefix = "/admin/reports";
  const [day, setDay] = useState(vnDay()),
    [compare, setCompare] = useState(vnDay(new Date(Date.now() - 86400000)));
  const [period, setPeriod] = useState("day");
  const [month, setMonth] = useState(vnDay().slice(0, 7));
  const [compareMonth, setCompareMonth] = useState(() => {
    const [y, m] = vnDay().split("-").map(Number);
    return new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 7);
  });
  const selectedPeriod = period === "month" ? month : day;
  const comparisonPeriod = period === "month" ? compareMonth : compare;
  const { data: reportData } = useData(period === "month"
    ? prefix + "/monthly?month=" + month + "&compare=" + compareMonth
    : prefix + "/daily?date=" + day + "&compare=" + compare);
  const data = reportData?.selected?.[period === "month" ? "month" : "day"] === selectedPeriod
    && reportData?.comparison?.[period === "month" ? "month" : "day"] === comparisonPeriod ? reportData : null;
  const exportCSV = () => {
    const rows = [
      [
        "Ngày",
        "Đơn đã giao",
        "Doanh thu hàng",
        "Phí giao",
        "Giá vốn",
        "Lãi gộp",
        "Dòng thiếu giá vốn",
        "VAT",
      ],
      ...(data?.daily ?? []).map((r: Row) => [
        r.day,
        r.orders,
        r.merchandise,
        r.shipping,
        r.cost ?? "",
        r.grossProfit ?? "",
        r.missingCostLines,
        r.vat,
      ]),
    ];
    const url = URL.createObjectURL(
      new Blob(["\ufeff" + rows.map((r) => r.map((cell: unknown) => '"' + String(cell ?? "").replaceAll('"', '""') + '"').join(",")).join("\n")], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "lai-gop-food-mart-" + selectedPeriod + ".csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <div className="page-heading"><div>
        <h2>Doanh thu và lãi gộp · Food Mart</h2>
        <p>Ghi nhận theo ngày giao thành công, giờ Việt Nam. Phí giao được tách riêng.</p>
      </div></div>
      <div className="tabs" role="group" aria-label="Kỳ báo cáo">
        <button className={period === "day" ? "active" : ""} aria-pressed={period === "day"} onClick={() => setPeriod("day")}>Theo ngày</button>
        <button className={period === "month" ? "active" : ""} aria-pressed={period === "month"} onClick={() => setPeriod("month")}>Theo tháng</button>
      </div>
      <div className="toolbar report-period-controls">
        <Field label={period === "month" ? "Tháng báo cáo" : "Ngày báo cáo"}>
          <input
            type={period === "month" ? "month" : "date"}
            value={selectedPeriod}
            onChange={(e) => e.target.value && (period === "month" ? setMonth(e.target.value) : setDay(e.target.value))}
          />
        </Field>
        <Field label="So sánh với">
          <input
            type={period === "month" ? "month" : "date"}
            value={comparisonPeriod}
            onChange={(e) => e.target.value && (period === "month" ? setCompareMonth(e.target.value) : setCompare(e.target.value))}
          />
        </Field>
        <button disabled={!data} onClick={exportCSV}>
          Xuất CSV
        </button>
      </div>
      {!data && <div className="spinner" role="status">Đang tải báo cáo…</div>}
      {data && (
        <>
          <p className="muted">{period === "month" ? `Tổng tháng ${month}; bảng bên dưới hiển thị từng ngày trong tháng.` : `7 ngày gần nhất: từ ${vnDateOffset(day, -6)} đến ${day}.`}</p>
          <div className="report-totals">
            {[
              ["orders", "Đơn đã giao"],
              ["merchandise", "Doanh thu hàng"],
              ["cost", "Giá vốn"],
              ["grossProfit", "Lãi gộp"],
              ["shipping", "Phí giao"],
              ["vat", "VAT"],
            ].map(([field, label]) => (
              <div key={field}>
                <p className="muted">{label}</p>
                <strong className="report-value">
                  {data.selected[field] === null
                    ? "Chưa đủ dữ liệu"
                    : field === "orders"
                      ? data.selected[field]
                      : money(data.selected[field])}
                </strong>
                {data.changes[field] && (
                  <p className="muted">
                    So với {comparisonPeriod}:{" "}
                    {data.changes[field].amount !== null && (Number(data.changes[field].amount) > 0 ? "Tăng " : Number(data.changes[field].amount) < 0 ? "Giảm " : "Không đổi ")}
                    {data.changes[field].amount === null
                      ? "Chưa đủ dữ liệu"
                      : field === "orders"
                        ? String(data.changes[field].amount).replace(/^-/, "")
                        : money(String(data.changes[field].amount).replace(/^-/, ""))}
                    {data.changes[field].percent !== null
                      ? " (" + data.changes[field].percent + "%)"
                      : ""}
                  </p>
                )}
              </div>
            ))}
          </div>
          {data.selected.missingCostLines > 0 && (
            <p className="notice warn">
              Có {data.selected.missingCostLines} dòng hàng lịch sử chưa biết
              giá vốn; chưa thể tính lãi gộp đầy đủ.
            </p>
          )}
          {data.selected.legacyPaymentOrders > 0 && <p className="notice warn">Có {data.selected.legacyPaymentOrders} đơn lịch sử chưa có thông tin thanh toán; không tự ghi nhận đã thu hoặc đang nợ.</p>}
          <div className="panel table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ngày</th>
                  <th>Đơn đã giao</th>
                  <th>Doanh thu</th>
                  <th>Giá vốn</th>
                  <th>Lãi gộp</th>
                  <th>Phí giao</th>
                  <th>VAT</th>
                </tr>
              </thead>
              <tbody>
                {data.daily.map((r: Row) => (
                  <tr key={r.day}>
                    <td>{r.day}</td>
                    <td>{r.orders}</td>
                    <td>{money(r.merchandise)}</td>
                    <td>
                      {r.cost === null ? "Chưa đủ dữ liệu" : money(r.cost)}
                    </td>
                    <td>
                      {r.grossProfit === null
                        ? "Chưa đủ dữ liệu"
                        : money(r.grossProfit)}
                    </td>
                    <td>{money(r.shipping)}</td>
                    <td>{money(r.vat)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
