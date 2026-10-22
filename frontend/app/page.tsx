"use client";

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
} from "@fortawesome/free-solid-svg-icons";

type Row = Record<string, any>;
type Session = { user: Row; csrfToken: string; demo: boolean };
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
// The catalog model follows the socket cursor. HTTP refreshes cannot overwrite
// a newer streamed state or race the snapshot/live boundary.
let catalogOwner = "";
let catalogModel: Row[] | null = null;
let followedProducts = new Set<string>();
const catalogChanged = () => window.dispatchEvent(new Event("ro:catalog"));
async function api(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
): Promise<any> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch("/api/v1" + path, {
    method,
    headers,
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
const date = (n: string) => (n ? new Date(n).toLocaleString("vi-VN") : "");
const statuses: Record<string, string> = {
  PENDING: "Chờ duyệt",
  APPROVED: "Đã duyệt",
  PREPARING: "Đang chuẩn bị",
  SHIPPING: "Đang giao",
  DELIVERED: "Đã giao",
  REJECTED: "Từ chối",
  CANCELLED: "Đã hủy",
  NEW: "Mới gửi",
  RECEIVED: "Đã tiếp nhận",
  QUOTED: "Đã báo giá",
  ACCEPTED: "Đã chấp thuận",
  CONVERTED: "Đã tạo đơn",
  OPEN: "Đang mở",
  CLOSED: "Đã đóng",
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
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const old = document.activeElement as HTMLElement;
    const root = ref.current;
    const focusable = () =>
      Array.from(
        root?.querySelectorAll<HTMLElement>(
          'button,input,select,textarea,[tabindex="0"]',
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
      old?.focus();
    };
  }, []);
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
    [loading, setLoading] = useState(true),
    [tab, setTab] = useState("catalog"),
    [online, setOnline] = useState(false),
    [refresh, setRefresh] = useState(0),
    [toast, setToast] = useState<{ message: string; error: boolean } | null>(
      null,
    ),
    [pending, setPending] = useState<Row[]>([]);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const notify = useCallback(
    (message: string, error = false) => setToast({ message, error }),
    [],
  );
  const reload = useCallback(() => setRefresh((x) => x + 1), []);
  useEffect(() => {
    api("/auth/session")
      .then((s) => {
        csrfToken = s.csrfToken;
        setSession(s);
        setTab(s.user.role === "ADMIN" ? "orders" : "catalog");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(null), 7000);
      return () => clearTimeout(id);
    }
  }, [toast]);
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
        /^\/(admin\/)?orders\//.test(path) ||
        path === "/admin/inventory-adjustments" ||
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
        if (e.path === "/orders")
          sessionStorage.removeItem("ro-cart-" + sessionRef.current!.user.id);
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
  if (loading)
    return <div className="spinner">Đang kiểm tra phiên đăng nhập…</div>;
  if (!session)
    return (
      <>
        <Auth
          onLogin={(s) => {
            csrfToken = s.csrfToken;
            setSession(s);
            setTab(s.user.role === "ADMIN" ? "orders" : "catalog");
          }}
        />
        {toast && (
          <div role="alert" className={"toast " + (toast.error ? "error" : "")}>
            {toast.message}
          </div>
        )}
      </>
    );
  const admin = session.user.role === "ADMIN";
  const nav = admin
    ? [
        ["orders", "Xử lý đơn", faListCheck],
        ["offers", "Đợt mở bán", faBasketShopping],
        ["products", "Sản phẩm", faBoxOpen],
        ["requests", "Yêu cầu hàng", faClipboardList],
        ["chat", "Tin nhắn", faCommentDots],
        ["users", "Khách hàng", faUsers],
        ["config", "Cấu hình", faSliders],
        ["reports", "Báo cáo", faChartColumn],
        ["audit", "Nhật ký", faListCheck],
      ]
    : [
        ["catalog", "Hàng trong ngày", faBasketShopping],
        ["orders", "Đơn của tôi", faListCheck],
        ["requests", "Yêu cầu hàng", faClipboardList],
        ["chat", "Nhắn người bán", faCommentDots],
        ["notifications", "Thông báo", faBell],
        ["profile", "Hồ sơ & địa chỉ", faUser],
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
        <div className="brand">
          <span className="brand-mark">
            <Icon icon={faBasketShopping} />
          </span>
          RealtimeOrders
        </div>
        <div className="header-meta">
          <span className="connection" role="status">
            <i className={"dot " + (online ? "online" : "")} />
            {online ? "Đang đồng bộ" : "Đang kết nối lại"}
          </span>
          <span className="user-name">
            {session.user.display_name} · {admin ? "Quản trị" : "Khách hàng"}
          </span>
          <button
            className="ghost"
            aria-label="Đăng xuất"
            onClick={async () => {
              try {
                await api("/auth/logout", "POST", {});
                csrfToken = "";
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
      <div className="shell">
        <aside className="nav">
          <div className="nav-label">
            {admin ? "Điều hành bán hàng" : "Mua sắm & hỗ trợ"}
          </div>
          {nav.map(([id, label, icon]) => (
            <button
              key={String(id)}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(String(id))}
            >
              <Icon icon={icon as any} />
              {String(label)}
            </button>
          ))}
          <div className="nav-foot">
            Nhóm 17 · Lập trình mạng
            <br />
            Dữ liệu lưu trên máy chủ
          </div>
        </aside>
        <main>
          {session.demo && (
            <div className="notice warn">
              Môi trường demo · Hàng, khu giao và tài khoản là dữ liệu mẫu. OTP
              hiển thị trên màn hình, chưa gửi SMS thật.
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
          {tab === "catalog" && <Catalog />}
          {tab === "orders" && <Orders admin={admin} />}{" "}
          {tab === "requests" && <Requests admin={admin} />}{" "}
          {tab === "chat" && <Chat admin={admin} />}{" "}
          {tab === "notifications" && <Notifications />}{" "}
          {tab === "profile" && <Profile />} {tab === "offers" && <Offers />}{" "}
          {tab === "products" && <Products />} {tab === "users" && <Users />}{" "}
          {tab === "config" && <Configuration />}{" "}
          {tab === "reports" && <Reports />} {tab === "audit" && <Audit />}
        </main>
      </div>
      {toast && (
        <div role="alert" className={"toast " + (toast.error ? "error" : "")}>
          <span>{toast.message}</span>
          <button
            className="ghost"
            onClick={() => setToast(null)}
            aria-label="Đóng thông báo"
          >
            ✕
          </button>
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
    [code, setCode] = useState("");
  const changeMode = (m: string) => {
    setMode(m);
    setError("");
    setChallenge(null);
    setTicket("");
    setPassword("");
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
          Đặt hàng rõ ràng.
          <br />
          Nhận hàng đúng hẹn.
        </h1>
        <p>
          Xem hàng đang bán, theo dõi đơn và trao đổi trực tiếp với người bán
          trong cùng một nơi.
        </p>
        <div className="muted">Bài tập lớn Lập trình mạng · Nhóm 17</div>
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
                <p>Mã xác minh đã được tạo cho {identifier}.</p>
                {challenge.demo && challenge.demoCode && (
                  <div className="notice warn">
                    OTP demo:{" "}
                    <strong data-testid="demo-code">
                      {challenge.demoCode}
                    </strong>{" "}
                    · Chưa gửi SMS thật
                  </div>
                )}
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
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    setChallenge(null);
                    setCode("");
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
            <button className="primary" disabled={busy}>
              {busy
                ? "Đang xử lý…"
                : mode === "login"
                  ? "Đăng nhập"
                  : !challenge
                    ? "Nhận mã xác minh"
                    : !ticket
                      ? "Xác minh mã"
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
  }, [path, refresh, notify]);
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
}: {
  title: string;
  sub: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">RealtimeOrders</div>
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      {children}
    </div>
  );
}

function Catalog() {
  const { online, mutate, notify, session } = useApp();
  const { data: offers } = useData("/catalog/offers"),
    { data: addresses } = useData("/me/addresses"),
    { data: delivery } = useData("/delivery/options");
  const [cart, setCart] = useState<Row[]>(() => {
      try {
        return JSON.parse(
          sessionStorage.getItem("ro-cart-" + session.user.id) ?? "[]",
        );
      } catch {
        return [];
      }
    }),
    [values, setValues] = useState<Record<string, string>>({}),
    [address, setAddress] = useState(""),
    [policy, setPolicy] = useState(""),
    [slot, setSlot] = useState(""),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    sessionStorage.setItem("ro-cart-" + session.user.id, JSON.stringify(cart));
  }, [cart, session.user.id]);
  const chosenAddress =
    (addresses ?? []).find((a: Row) => a.id === address) ?? addresses?.[0];
  useEffect(() => {
    const resolved = (event: Event) => {
      if ((event as CustomEvent).detail.path === "/orders") {
        setCart([]);
        setNote("");
      }
    };
    window.addEventListener("ro:operation-resolved", resolved);
    return () => window.removeEventListener("ro:operation-resolved", resolved);
  }, []);
  const policies = (delivery?.policies ?? []).filter(
      (p: Row) => p.zone_id === chosenAddress?.zone_id,
    ),
    selectedLive = policies.find((p: Row) => p.id === policy) ?? policies[0];
  const slots = (delivery?.pickupSlots ?? []).filter(
      (s: Row) => s.zone_id === chosenAddress?.zone_id,
    ),
    slotLive = slots.find((s: Row) => s.id === slot) ?? slots[0];
  const [policyQuote, setPolicyQuote] = useState<Row | null>(null),
    [slotQuote, setSlotQuote] = useState<Row | null>(null);
  useEffect(() => {
    if (selectedLive)
      setPolicyQuote({ ...selectedLive, addressId: chosenAddress?.id });
  }, [selectedLive?.id, chosenAddress?.id]);
  useEffect(() => {
    if (slotLive) setSlotQuote(slotLive);
  }, [slotLive?.id]);
  const selected =
    policyQuote?.id === selectedLive?.id ? policyQuote : selectedLive;
  const selectedSlot = slotQuote?.id === slotLive?.id ? slotQuote : slotLive;
  const shippingStale =
    !!selected &&
    (String(selected.version) !== String(selectedLive?.version) ||
      (selected.method === "COLLECTIVE" &&
        String(selectedSlot?.version) !== String(slotLive?.version)));
  const subtotal = cart.reduce(
      (sum: bigint, c) => sum + lineMoney(c.unit_price, c.quantity),
      BigInt(0),
    ),
    fee = BigInt(String(selected?.shipping_fee ?? 0)),
    stale = cart.some(
      (c) =>
        offers &&
        !offers.some(
          (o: Row) => o.id === c.id && o.price_version === c.price_version,
        ),
    );
  const addCart = (offer: Row) => {
    const quantity = values[offer.id] ?? offer.quantity_step;
    if (!/^\d+(\.\d{1,3})?$/.test(String(quantity)) || Number(quantity) <= 0) {
      notify("Nhập số lượng hợp lệ", true);
      return;
    }
    setCart((old) => [
      ...old.filter((c) => c.id !== offer.id),
      { ...offer, quantity },
    ]);
    notify("Đã cập nhật giỏ hàng");
  };
  const submit = async () => {
    if (!selected || !chosenAddress) return;
    setBusy(true);
    try {
      await mutate("/orders", {
        clientOrderId: crypto.randomUUID(),
        addressId: chosenAddress.id,
        deliveryMethod: selected.method,
        policyVersion: String(selected.version),
        pickupSlotId: selectedSlot?.id,
        pickupSlotVersion: String(selectedSlot?.version ?? ""),
        note,
        items: cart.map((c) => ({
          offerId: c.id,
          quantity: c.quantity,
          expectedPriceVersion: String(c.price_version),
        })),
      });
      setCart([]);
      setNote("");
      notify("Đơn đã gửi và đang chờ người bán duyệt.");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Heading
        title="Hàng trong ngày"
        sub="Giá dành cho nhóm của bạn. Tồn kho cập nhật khi người bán duyệt đơn."
      />
      <div className="split">
        <section className="panel">
          <div className="panel-head">
            <h2>Đang mở bán</h2>
            <span className="muted">{offers?.length ?? 0} mặt hàng</span>
          </div>
          {!offers ? (
            <div className="spinner">Đang lấy hàng…</div>
          ) : !offers.length ? (
            <Empty title="Chưa có đợt mở bán">
              Quay lại sau hoặc gửi yêu cầu mặt hàng.
            </Empty>
          ) : (
            <table className="catalog-table">
              <thead>
                <tr>
                  <th>Mặt hàng</th>
                  <th>Giá / đơn vị</th>
                  <th>Còn kho</th>
                  <th>Đang chờ</th>
                  <th>Số lượng</th>
                </tr>
              </thead>
              <tbody>
                {offers.map((o: Row) => (
                  <tr key={o.id} data-offer-id={o.id}>
                    <td>
                      <div className="product-cell">
                        {o.images?.[0] ? (
                          <img
                            className="product-thumb"
                            src={"/api/v1/media/" + o.images[0]}
                            alt={o.name}
                          />
                        ) : (
                          <div className="product-thumb">
                            <Icon icon={faBoxOpen} />
                          </div>
                        )}
                        <div className="product-title">
                          {o.name}
                          <div className="product-subtitle">
                            {o.description}
                          </div>
                          <button
                            className="ghost small"
                            aria-label={
                              (o.subscribed ? "Bỏ theo dõi " : "Theo dõi ") +
                              o.name
                            }
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
                            <Icon icon={faHeart} />{" "}
                            {o.subscribed ? "Đang quan tâm" : "Quan tâm"}
                          </button>
                        </div>
                      </div>
                    </td>
                    <td data-label={"Giá / " + o.unit} className="money">
                      {money(o.unit_price)}
                    </td>
                    <td data-label="Còn trong kho">
                      {qty(o.available_qty)} {o.unit}
                    </td>
                    <td>
                      <span>
                        {qty(o.pending_qty)} {o.unit}
                      </span>
                      <div className="product-subtitle">
                        {o.pending_customers} khách chờ · {o.approved_orders}{" "}
                        đơn đã duyệt
                      </div>
                    </td>
                    <td>
                      <div className="buy-controls">
                        <input
                          className="qty"
                          aria-label={"Số lượng " + o.name}
                          type="number"
                          min={o.quantity_step}
                          step={o.quantity_step}
                          max={o.available_qty}
                          value={values[o.id] ?? o.quantity_step}
                          onChange={(e) =>
                            setValues({ ...values, [o.id]: e.target.value })
                          }
                        />
                        <button
                          className="small"
                          disabled={!online || Number(o.available_qty) <= 0}
                          onClick={() => addCart(o)}
                        >
                          Thêm
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="summary">
          <div className="row-heading">
            <h2>Đơn đang soạn</h2>
            <span className="muted">{cart.length} món</span>
          </div>
          {!cart.length ? (
            <p className="muted" style={{ margin: "18px 0" }}>
              Chọn số lượng rồi thêm hàng vào đơn.
            </p>
          ) : (
            <>
              {cart.map((c) => (
                <div className="cart-line" key={c.id}>
                  <div>
                    <strong>{c.name}</strong>
                    <div className="muted">
                      {qty(c.quantity)} {c.unit} × {money(c.unit_price)}
                    </div>
                  </div>
                  <button
                    className="ghost small"
                    aria-label={"Bỏ " + c.name}
                    onClick={() => setCart(cart.filter((x) => x.id !== c.id))}
                  >
                    <Icon icon={faTrash} />
                  </button>
                </div>
              ))}
            </>
          )}
          {stale && (
            <div className="notice warn">
              Giá hoặc đợt bán đã thay đổi.{" "}
              <button
                className="small"
                onClick={() =>
                  setCart(
                    cart
                      .map((c) => ({
                        ...offers.find((o: Row) => o.id === c.id),
                        quantity: c.quantity,
                      }))
                      .filter((c) => c.id),
                  )
                }
              >
                Cập nhật và xem lại tổng
              </button>
            </div>
          )}
          <div className="form" style={{ marginTop: 18 }}>
            <Field label="Địa chỉ nhận">
              <select
                value={chosenAddress?.id ?? ""}
                onChange={(e) => {
                  setAddress(e.target.value);
                  setPolicy("");
                }}
              >
                <option value="" disabled>
                  Chọn địa chỉ
                </option>
                {addresses?.map((a: Row) => (
                  <option key={a.id} value={a.id}>
                    {a.recipient_name} · {a.address_line}
                  </option>
                ))}
              </select>
            </Field>
            {!addresses?.length && (
              <small>Thêm địa chỉ trong Hồ sơ & địa chỉ trước khi đặt.</small>
            )}
            {shippingStale && (
              <div className="notice warn">
                Phí hoặc điều kiện giao đã thay đổi. Tổng hiện tại vẫn giữ báo
                giá trước.{" "}
                <button
                  className="small"
                  onClick={() => {
                    setPolicyQuote(selectedLive);
                    setSlotQuote(slotLive);
                  }}
                >
                  Cập nhật phí và xem lại tổng
                </button>
              </div>
            )}
            <Field label="Cách giao">
              <select
                value={selected?.id ?? ""}
                onChange={(e) => setPolicy(e.target.value)}
              >
                <option value="" disabled>
                  Chọn cách giao
                </option>
                {policies.map((p: Row) => (
                  <option key={p.id} value={p.id}>
                    {p.method === "COLLECTIVE"
                      ? "Giao tập trung · miễn phí"
                      : "Giao riêng · " + money(p.shipping_fee)}
                  </option>
                ))}
              </select>
            </Field>
            {selected?.method === "COLLECTIVE" && (
              <Field label="Điểm và giờ nhận">
                <select
                  value={selectedSlot?.id ?? ""}
                  onChange={(e) => setSlot(e.target.value)}
                >
                  {slots.map((s: Row) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Ghi chú cho người bán">
              <textarea
                maxLength={1000}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
          </div>
          <div className="summary-row">
            <span>Tiền hàng</span>
            <span>{money(subtotal)}</span>
          </div>
          <div className="summary-row">
            <span>Phí giao</span>
            <span>{money(fee)}</span>
          </div>
          <div className="summary-row total">
            <span>Tổng cộng</span>
            <span>{money(subtotal + fee)}</span>
          </div>
          {selected && subtotal < Number(selected.minimum_subtotal) && (
            <p className="notice warn">
              Giao riêng cần tối thiểu {money(selected.minimum_subtotal)} tiền
              hàng.
            </p>
          )}
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={
              !online ||
              busy ||
              !cart.length ||
              stale ||
              shippingStale ||
              !selected ||
              !chosenAddress ||
              subtotal < Number(selected?.minimum_subtotal) ||
              (selected?.method === "COLLECTIVE" && !selectedSlot)
            }
            onClick={submit}
          >
            {busy ? "Đang gửi…" : "Gửi đơn chờ duyệt"}
          </button>
          <p className="footer-note">
            Gửi đơn chưa giữ hàng và chưa trừ kho. Người bán sẽ kiểm tra và xác
            nhận sau.
          </p>
        </section>
      </div>
    </>
  );
}

function Orders({ admin }: { admin: boolean }) {
  const { mutate, online, notify } = useApp();
  const [page, setPage] = useState(0),
    [filter, setFilter] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [reason, setReason] = useState("");
  const { data: orders } = useData(
    (admin ? "/admin" : "") +
      "/orders?page=" +
      page +
      (filter ? "&status=" + filter : ""),
  );
  useEffect(() => {
    if (selected && orders) {
      const fresh = orders.find((o: Row) => o.id === selected.id);
      if (fresh) setSelected(fresh);
    }
  }, [orders]);
  const action = async (o: Row, act: string, extra: Row = {}) => {
    setBusy(true);
    try {
      const result = await mutate(
        (admin ? "/admin" : "") + "/orders/" + o.id + "/" + act,
        { expectedVersion: String(o.version), reason, ...extra },
      );
      setSelected(result);
      setReason("");
      notify("Đã cập nhật đơn");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Heading
        title={admin ? "Xử lý đơn hàng" : "Đơn của tôi"}
        sub={
          admin
            ? "Kiểm tra tồn kho, duyệt đơn và theo dõi quá trình giao."
            : "Theo dõi xác nhận, giao hàng và các yêu cầu hủy."
        }
      />
      <div className="toolbar">
        <select
          aria-label="Lọc trạng thái đơn"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        >
          <option value="">Tất cả trạng thái</option>
          {[
            "PENDING",
            "APPROVED",
            "PREPARING",
            "SHIPPING",
            "DELIVERED",
            "CANCELLED",
            "REJECTED",
          ].map((s) => (
            <option key={s} value={s}>
              {statuses[s]}
            </option>
          ))}
        </select>
        <span className="muted">Trang {page + 1}</span>
      </div>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Đơn / thời gian</th>
              <th>Mặt hàng</th>
              <th>Thanh toán COD</th>
              <th>Trạng thái</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {orders?.map((o: Row) => (
              <tr key={o.id}>
                <td>
                  <strong>#{o.id.slice(0, 8).toUpperCase()}</strong>
                  <div className="date">{date(o.created_at)}</div>
                  {admin && (
                    <div className="muted">
                      {o.address_snapshot.recipient_name}
                    </div>
                  )}
                </td>
                <td>
                  {o.items.map((i: Row) => (
                    <div key={i.id}>
                      {i.product_name_snapshot}{" "}
                      <span className="muted">
                        × {qty(i.quantity)} {i.unit_snapshot}
                      </span>
                    </div>
                  ))}
                </td>
                <td className="money">{money(o.total)}</td>
                <td>
                  <Status value={o.status} />
                  {o.cancellation_requests.some(
                    (x: Row) => x.state === "OPEN",
                  ) && <div className="status PENDING">Có yêu cầu hủy</div>}
                </td>
                <td>
                  <button
                    className="small"
                    onClick={() => {
                      setSelected(o);
                      setReason("");
                    }}
                  >
                    Chi tiết
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {orders?.length === 0 && <Empty title="Chưa có đơn phù hợp" />}
        {!orders && <div className="spinner">Đang lấy đơn…</div>}
      </div>
      <div className="toolbar">
        <button disabled={!page} onClick={() => setPage(page - 1)}>
          Trang trước
        </button>
        <button
          disabled={!orders || orders.length < 50}
          onClick={() => setPage(page + 1)}
        >
          Trang sau
        </button>
      </div>
      {selected && (
        <Modal
          title={"Đơn #" + selected.id.slice(0, 8).toUpperCase()}
          close={() => setSelected(null)}
        >
          <div className="row-heading">
            <Status value={selected.status} />
            <span className="muted">Phiên bản {selected.version}</span>
          </div>
          <div className="detail-grid">
            <div>
              <strong>Người nhận</strong>
              <p>{selected.address_snapshot.recipient_name}</p>
              <p>{selected.address_snapshot.phone_e164}</p>
              <p>{selected.address_snapshot.address_line}</p>
            </div>
            <div>
              <strong>Giao hàng</strong>
              <p>
                {selected.delivery_method === "COLLECTIVE"
                  ? "Giao tập trung"
                  : "Giao riêng"}
              </p>
              <p>{selected.delivery_snapshot.pickupSlot?.name}</p>
              <p>Giá nhóm: {selected.group_snapshot.name}</p>
            </div>
          </div>
          <div className="panel table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Mặt hàng</th>
                  <th>Số lượng</th>
                  <th>Đơn giá</th>
                  <th>Thành tiền</th>
                </tr>
              </thead>
              <tbody>
                {selected.items.map((i: Row) => (
                  <tr key={i.id}>
                    <td>{i.product_name_snapshot}</td>
                    <td>
                      {qty(i.quantity)} {i.unit_snapshot}
                    </td>
                    <td>{money(i.unit_price)}</td>
                    <td>{money(i.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="summary-row">
            <span>Phí giao</span>
            <span>{money(selected.shipping_fee)}</span>
          </div>
          <div className="summary-row total">
            <span>Tổng COD</span>
            <span>{money(selected.total)}</span>
          </div>
          {selected.note && <p>Ghi chú: {selected.note}</p>}
          <h3 style={{ marginTop: 20 }}>Lịch sử xử lý</h3>
          <div className="timeline">
            {selected.history.map((h: Row) => (
              <div key={h.id}>
                <Status value={h.to_status} /> · {date(h.created_at)}
                {h.reason && <p>{h.reason}</p>}
              </div>
            ))}
          </div>
          {selected.cancellation_requests.map((c: Row) => (
            <div className="notice warn" key={c.id}>
              Yêu cầu hủy: {c.reason}
              <br />
              {c.state === "OPEN"
                ? "Đang chờ quản trị xác nhận"
                : c.state === "ACCEPTED"
                  ? "Đã chấp thuận và hoàn kho"
                  : "Đã từ chối hủy"}
              {c.decision_note && <p>{c.decision_note}</p>}
            </div>
          ))}
          {["PENDING", "APPROVED", "PREPARING", "SHIPPING"].includes(
            selected.status,
          ) && (
            <>
              <Field label="Lý do / ghi chú xử lý">
                <textarea
                  value={reason}
                  maxLength={1000}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
              <div className="actions" style={{ marginTop: 14 }}>
                {admin ? (
                  <>
                    {selected.status === "PENDING" && (
                      <>
                        <button
                          className="primary"
                          disabled={!online || busy}
                          onClick={() => action(selected, "approve")}
                        >
                          Duyệt toàn bộ đơn
                        </button>
                        <button
                          disabled={!online || busy}
                          onClick={() => action(selected, "reject")}
                        >
                          Từ chối
                        </button>
                      </>
                    )}
                    {selected.cancellation_requests.some(
                      (x: Row) => x.state === "OPEN",
                    ) ? (
                      <>
                        <button
                          className="danger"
                          disabled={!online || busy}
                          onClick={() =>
                            action(selected, "decide-cancel", { accept: true })
                          }
                        >
                          Chấp thuận hủy & hoàn kho
                        </button>
                        <button
                          disabled={!online || busy}
                          onClick={() =>
                            action(selected, "decide-cancel", { accept: false })
                          }
                        >
                          Từ chối yêu cầu hủy
                        </button>
                      </>
                    ) : (
                      ["APPROVED", "PREPARING", "SHIPPING"].includes(
                        selected.status,
                      ) && (
                        <button
                          className="primary"
                          disabled={!online || busy}
                          onClick={() =>
                            action(selected, "transition", {
                              status: (
                                {
                                  APPROVED: "PREPARING",
                                  PREPARING: "SHIPPING",
                                  SHIPPING: "DELIVERED",
                                } as Row
                              )[selected.status],
                            })
                          }
                        >
                          {
                            (
                              {
                                APPROVED: "Bắt đầu chuẩn bị",
                                PREPARING: "Bàn giao vận chuyển",
                                SHIPPING: "Xác nhận đã giao",
                              } as Row
                            )[selected.status]
                          }
                        </button>
                      )
                    )}
                  </>
                ) : (
                  <>
                    {selected.status === "PENDING" && (
                      <button
                        className="danger"
                        disabled={!online || busy}
                        onClick={() => action(selected, "cancel")}
                      >
                        Hủy đơn đang chờ
                      </button>
                    )}
                    {["APPROVED", "PREPARING"].includes(selected.status) &&
                      !selected.cancellation_requests.some(
                        (x: Row) => x.state === "OPEN",
                      ) && (
                        <button
                          disabled={!online || busy || !reason.trim()}
                          onClick={() =>
                            action(selected, "cancellation-requests")
                          }
                        >
                          Gửi yêu cầu hủy
                        </button>
                      )}
                  </>
                )}
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  );
}

function Profile() {
  const { session, mutate, notify, online, setSession } = useApp(),
    { data: addresses } = useData("/me/addresses"),
    { data: delivery } = useData("/delivery/options");
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
        { ...editing, expectedVersion: String(editing?.version ?? "") },
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
                  zoneId: delivery?.zones[0]?.id,
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
                      zoneId: a.zone_id,
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
            <Field label="Khu vực giao" wide>
              <select
                required
                value={editing.zoneId ?? ""}
                onChange={(e) =>
                  setEditing({ ...editing, zoneId: e.target.value })
                }
              >
                <option value="" disabled>
                  Chọn khu vực
                </option>
                {delivery?.zones.map((z: Row) => (
                  <option key={z.id} value={z.id}>
                    {z.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Địa chỉ cụ thể" wide>
              <textarea
                required
                minLength={5}
                maxLength={500}
                value={editing.addressLine}
                onChange={(e) =>
                  setEditing({ ...editing, addressLine: e.target.value })
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

function Requests({ admin }: { admin: boolean }) {
  const { data } = useData((admin ? "/admin" : "") + "/product-requests");
  const { mutate, notify, online } = useApp();
  const [creating, setCreating] = useState(false),
    [form, setForm] = useState<Row>({
      itemName: "",
      quantity: "1",
      unitLabel: "kg",
      note: "",
    }),
    [selected, setSelected] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [quote, setQuote] = useState(false);
  const [context, setContext] = useState<Row | null>(null),
    [deliveryChoice, setDeliveryChoice] = useState<Row>({});
  useEffect(() => {
    if (selected && data) {
      const next = data.find((d: Row) => d.id === selected.id);
      if (next) setSelected(next);
    }
  }, [data]);
  useEffect(() => {
    if (!selected) return;
    let live = true;
    const get = admin
      ? api("/admin/users/" + selected.customer_id + "/delivery-context")
      : Promise.all([api("/me/addresses"), api("/delivery/options")]).then(
          ([addresses, options]) => ({ addresses, ...options }),
        );
    get
      .then((d) => {
        if (live) setContext(d);
      })
      .catch((e) => notify(e.message, true));
    return () => {
      live = false;
    };
  }, [selected?.id, admin, notify]);
  const act = async (action: string, extra: Row = {}) => {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await mutate(
        (admin ? "/admin" : "") +
          "/product-requests/" +
          selected.id +
          "/" +
          action,
        { expectedVersion: String(selected.version), ...extra },
      );
      setSelected(result);
      notify("Đã cập nhật yêu cầu");
    } catch {
    } finally {
      setBusy(false);
    }
  };
  const latest = selected?.quotes[0];
  const agreed = latest?.delivery_snapshot;
  const quoteAddresses = (context?.addresses ?? []).filter(
    (a: Row) => !agreed?.zoneId || a.zone_id === agreed.zoneId,
  );
  const addr =
    quoteAddresses.find((a: Row) => a.id === deliveryChoice.addressId) ??
    quoteAddresses[0];
  const deliveryBody = {
    addressId: addr?.id,
    deliveryMethod: agreed?.method,
    policyVersion: String(agreed?.policyVersion ?? ""),
    pickupSlotId: agreed?.pickupSlot?.id,
    pickupSlotVersion: String(agreed?.pickupSlot?.version ?? ""),
  };
  return (
    <>
      <Heading
        title="Yêu cầu mặt hàng"
        sub="Trao đổi hàng chưa có sẵn, nhận báo giá rồi chấp thuận trước khi tạo đơn."
      >
        {!admin && (
          <button
            className="primary"
            disabled={!online}
            onClick={() => setCreating(true)}
          >
            <Icon icon={faPlus} /> Gửi yêu cầu
          </button>
        )}
      </Heading>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Mặt hàng cần mua</th>
              <th>Số lượng</th>
              <th>Ngày gửi</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.map((r: Row) => (
              <tr key={r.id}>
                <td>
                  <strong>{r.item_name}</strong>
                  <div className="product-subtitle">{r.note}</div>
                </td>
                <td>
                  {qty(r.quantity)} {r.unit_label}
                </td>
                <td className="date">{date(r.created_at)}</td>
                <td>
                  <Status value={r.status} />
                  {r.linked_order && (
                    <div>
                      <Status value={r.linked_order.status} />
                    </div>
                  )}
                </td>
                <td>
                  <button
                    onClick={() => {
                      setSelected(r);
                      setContext(null);
                      setQuote(false);
                    }}
                  >
                    Chi tiết
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.length === 0 && (
          <Empty title="Chưa có yêu cầu">
            Bạn có thể đề xuất mặt hàng và số lượng mong muốn.
          </Empty>
        )}
      </div>
      {creating && (
        <Modal title="Gửi yêu cầu mặt hàng" close={() => setCreating(false)}>
          <form
            className="form form-grid"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await mutate("/product-requests", form);
                setCreating(false);
                setForm({
                  itemName: "",
                  quantity: "1",
                  unitLabel: "kg",
                  note: "",
                });
                notify("Đã gửi yêu cầu tới người bán");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Tên mặt hàng" wide>
              <input
                required
                maxLength={150}
                value={form.itemName}
                onChange={(e) => setForm({ ...form, itemName: e.target.value })}
              />
            </Field>
            <Field label="Số lượng">
              <input
                type="number"
                min="0.001"
                step="0.001"
                required
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              />
            </Field>
            <Field label="Đơn vị mong muốn">
              <input
                required
                maxLength={40}
                value={form.unitLabel}
                onChange={(e) =>
                  setForm({ ...form, unitLabel: e.target.value })
                }
              />
            </Field>
            <Field label="Thông tin thêm" wide>
              <textarea
                maxLength={2000}
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
              />
            </Field>
            <button className="primary" disabled={!online || busy}>
              Gửi yêu cầu
            </button>
          </form>
        </Modal>
      )}
      {selected && (
        <Modal title={selected.item_name} close={() => setSelected(null)}>
          <div className="row-heading">
            <Status value={selected.status} />
            <span>
              {qty(selected.quantity)} {selected.unit_label}
            </span>
          </div>
          <p>{selected.note}</p>
          {selected.linked_order && (
            <div className="notice">
              Đã tạo đơn #{selected.linked_order.id.slice(0, 8)} ·{" "}
              <Status value={selected.linked_order.status} />
            </div>
          )}
          <h3 style={{ marginTop: 20 }}>Báo giá</h3>
          {!selected.quotes.length ? (
            <p className="muted">Chưa có báo giá.</p>
          ) : (
            selected.quotes.map((q: Row) => (
              <div className="list-row" key={q.id}>
                <strong>
                  Phiên bản {q.revision} ·{" "}
                  {q.item_snapshot?.productName ?? selected.item_name} ·{" "}
                  {money(q.unit_price)} /{" "}
                  {q.item_snapshot?.unitLabel ?? selected.unit_label}
                </strong>
                <p>
                  {qty(q.quantity)}{" "}
                  {q.item_snapshot?.unitLabel ?? selected.unit_label} · Phí giao{" "}
                  {money(q.shipping_fee)}
                </p>
                <p className="muted">
                  Hiệu lực đến {date(q.expires_at)}
                  {q.accepted_at ? " · Đã chấp thuận" : ""}
                </p>
              </div>
            ))
          )}
          <div className="actions" style={{ marginTop: 18 }}>
            {admin ? (
              <>
                {selected.status === "NEW" && (
                  <button
                    className="primary"
                    disabled={!online || busy}
                    onClick={() => act("receive")}
                  >
                    Tiếp nhận
                  </button>
                )}
                {["RECEIVED", "QUOTED"].includes(selected.status) && (
                  <button
                    className="primary"
                    disabled={!online || busy}
                    onClick={() => setQuote(!quote)}
                  >
                    Soạn báo giá
                  </button>
                )}
                {["NEW", "RECEIVED", "QUOTED"].includes(selected.status) && (
                  <button
                    className="danger"
                    disabled={!online || busy}
                    onClick={() => act("reject")}
                  >
                    Từ chối yêu cầu
                  </button>
                )}
              </>
            ) : (
              <>
                {selected.status === "QUOTED" && latest && (
                  <button
                    className="primary"
                    disabled={
                      !online ||
                      busy ||
                      new Date(latest.expires_at) < new Date()
                    }
                    onClick={() => act("accept-quote", { quoteId: latest.id })}
                  >
                    Chấp thuận báo giá mới nhất
                  </button>
                )}
                {["NEW", "RECEIVED", "QUOTED", "ACCEPTED"].includes(
                  selected.status,
                ) && (
                  <button
                    disabled={!online || busy}
                    onClick={() => act("cancel")}
                  >
                    Hủy yêu cầu
                  </button>
                )}
              </>
            )}
          </div>
          {!admin && selected.status === "ACCEPTED" && latest && (
            <>
              <hr />
              <div className="notice">
                Tạo đơn theo giá đã chấp thuận. Kho chỉ trừ khi quản trị duyệt
                đơn.
              </div>
              <div className="form">
                <Field label="Địa chỉ nhận">
                  <select
                    value={addr?.id ?? ""}
                    onChange={(e) =>
                      setDeliveryChoice({
                        ...deliveryChoice,
                        addressId: e.target.value,
                      })
                    }
                  >
                    {quoteAddresses.map((a: Row) => (
                      <option value={a.id} key={a.id}>
                        {a.address_line}
                      </option>
                    ))}
                  </select>
                </Field>
                <p>
                  Cách giao đã chốt:{" "}
                  {agreed?.method === "COLLECTIVE" ? "Tập trung" : "Giao riêng"}{" "}
                  · Phí {money(latest.shipping_fee)}
                  <br />
                  {agreed?.pickupSlot?.name}
                </p>
                <button
                  className="primary"
                  disabled={!online || busy || !addr || !agreed}
                  onClick={() =>
                    act("convert", {
                      quoteId: latest.id,
                      clientOrderId: crypto.randomUUID(),
                      ...deliveryBody,
                    })
                  }
                >
                  Tạo đơn chờ duyệt từ báo giá
                </button>
              </div>
            </>
          )}
          {quote && admin && context && (
            <QuoteForm
              request={selected}
              context={context}
              done={() => setQuote(false)}
            />
          )}
        </Modal>
      )}
    </>
  );
}

function QuoteForm({
  request,
  context,
  done,
}: {
  request: Row;
  context: Row;
  done: () => void;
}) {
  const { data: offers } = useData("/admin/offers");
  const { mutate, notify, online } = useApp();
  const [f, setF] = useState<Row>({
      offerId: "",
      quantity: request.quantity,
      unitPrice: "",
      expiresMinutes: "60",
      addressId: "",
      policyId: "",
      slotId: "",
    }),
    [busy, setBusy] = useState(false);
  const address =
      context.addresses.find((a: Row) => a.id === f.addressId) ??
      context.addresses[0],
    policies = context.policies.filter(
      (p: Row) => p.zone_id === address?.zone_id,
    ),
    policy = policies.find((p: Row) => p.id === f.policyId) ?? policies[0],
    slots = context.pickupSlots.filter(
      (s: Row) => s.zone_id === address?.zone_id,
    ),
    slot = slots.find((s: Row) => s.id === f.slotId) ?? slots[0];
  const field = (key: string, value: string) => setF({ ...f, [key]: value });
  return (
    <form
      className="form form-grid"
      style={{ marginTop: 24 }}
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await mutate("/admin/product-requests/" + request.id + "/quote", {
            expectedVersion: String(request.version),
            offerId: f.offerId,
            quantity: f.quantity,
            unitPrice: f.unitPrice,
            expiresMinutes: f.expiresMinutes,
            addressId: address?.id,
            deliveryMethod: policy?.method,
            policyVersion: String(policy?.version),
            pickupSlotId: slot?.id,
            pickupSlotVersion: String(slot?.version),
          });
          notify("Đã gửi báo giá");
          done();
        } catch {
        } finally {
          setBusy(false);
        }
      }}
    >
      <Field label="Đợt hàng đáp ứng" wide>
        <select
          required
          value={f.offerId}
          onChange={(e) => field("offerId", e.target.value)}
        >
          <option value="">Chọn đợt hàng</option>
          {offers
            ?.filter((o: Row) => o.status === "OPEN")
            .map((o: Row) => (
              <option key={o.id} value={o.id}>
                {o.name} · {o.batch_code}
              </option>
            ))}
        </select>
      </Field>
      <Field label="Số lượng">
        <input
          required
          type="number"
          step=".001"
          min=".001"
          value={f.quantity}
          onChange={(e) => field("quantity", e.target.value)}
        />
      </Field>
      <Field label="Đơn giá thỏa thuận (đ)">
        <input
          required
          type="number"
          min="0"
          step="1"
          value={f.unitPrice}
          onChange={(e) => field("unitPrice", e.target.value)}
        />
      </Field>
      <Field label="Địa chỉ khách" wide>
        <select
          required
          value={address?.id ?? ""}
          onChange={(e) => field("addressId", e.target.value)}
        >
          {context.addresses.map((a: Row) => (
            <option key={a.id} value={a.id}>
              {a.address_line}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Chính sách giao">
        <select
          required
          value={policy?.id ?? ""}
          onChange={(e) => field("policyId", e.target.value)}
        >
          {policies.map((p: Row) => (
            <option key={p.id} value={p.id}>
              {p.method === "COLLECTIVE" ? "Tập trung" : "Giao riêng"} ·{" "}
              {money(p.shipping_fee)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Hiệu lực (phút)">
        <input
          required
          type="number"
          min="1"
          max="1440"
          value={f.expiresMinutes}
          onChange={(e) => field("expiresMinutes", e.target.value)}
        />
      </Field>
      {policy?.method === "COLLECTIVE" && (
        <Field label="Điểm giao" wide>
          <select
            required
            value={slot?.id ?? ""}
            onChange={(e) => field("slotId", e.target.value)}
          >
            {slots.map((s: Row) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
      )}
      <button
        className="primary"
        disabled={!online || busy || !address || !policy}
      >
        Gửi báo giá
      </button>
    </form>
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
      : api("/conversations/me").then((c) => [c])
    )
      .then((c) => {
        if (live) {
          setConversations(c);
          setSelected((old) => old || c[0]?.id || "");
        }
      })
      .catch((e) => notify(e.message, true));
    return () => {
      live = false;
    };
  }, [admin, refresh, notify]);
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
              }}
            >
              {admin ? c.display_name : "Người bán"}
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

function Products() {
  const { data } = useData("/admin/products"),
    { data: categories } = useData("/admin/config/categories"),
    { data: units } = useData("/admin/config/units");
  const { mutate, notify, online } = useApp();
  const [form, setForm] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const edit = (p?: Row) =>
    setForm(
      p
        ? {
            ...p,
            categoryId: p.category_id,
            unitId: p.unit_id,
            quantityStep: p.quantity_step,
            assetIds: p.images.map((i: Row) => i.asset_id),
          }
        : {
            name: "",
            sku: "",
            description: "",
            categoryId: categories?.[0]?.id,
            unitId: units?.[0]?.id,
            quantityStep: "1",
            active: true,
            assetIds: [],
          },
    );
  return (
    <>
      <Heading
        title="Danh mục sản phẩm"
        sub="Quản lý SKU, đơn vị, bước số lượng và ảnh. Lịch sử đơn giữ nguyên dữ liệu cũ."
      >
        <button className="primary" disabled={!online} onClick={() => edit()}>
          <Icon icon={faPlus} /> Thêm sản phẩm
        </button>
      </Heading>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Tên sản phẩm</th>
              <th>Đơn vị / bước</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.map((p: Row) => (
              <tr key={p.id}>
                <td className="muted">{p.sku}</td>
                <td>
                  <strong>{p.name}</strong>
                  <div className="product-subtitle">{p.description}</div>
                </td>
                <td>
                  {units?.find((u: Row) => u.id === p.unit_id)?.label} ·{" "}
                  {qty(p.quantity_step)}
                </td>
                <td>{p.active ? "Đang dùng" : "Ngừng dùng"}</td>
                <td>
                  <button className="small" onClick={() => edit(p)}>
                    Sửa
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {form && (
        <Modal
          title={form.id ? "Sửa sản phẩm" : "Thêm sản phẩm"}
          close={() => setForm(null)}
        >
          <form
            className="form form-grid"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await mutate(
                  "/admin/products" + (form.id ? "/" + form.id : ""),
                  { ...form, expectedVersion: String(form.version ?? "") },
                  form.id ? "PATCH" : "POST",
                );
                setForm(null);
                notify("Đã lưu sản phẩm");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Tên sản phẩm" wide>
              <input
                required
                maxLength={150}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Mã SKU">
              <input
                required
                maxLength={64}
                value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
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
                accept="image/png,image/jpeg,image/webp"
                disabled={busy || form.assetIds.length >= 5}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setBusy(true);
                  try {
                    const img = await uploadImage(file, "PRODUCT");
                    setForm({ ...form, assetIds: [...form.assetIds, img.id] });
                  } catch (e) {
                    notify((e as Error).message, true);
                  } finally {
                    setBusy(false);
                  }
                }}
              />
            </Field>
            <div className="actions wide">
              {form.assetIds.map((id: string) => (
                <div key={id}>
                  <img
                    src={"/api/v1/media/" + id}
                    alt="Ảnh sản phẩm"
                    width={64}
                    height={64}
                  />
                  <button
                    type="button"
                    className="small"
                    onClick={() =>
                      setForm({
                        ...form,
                        assetIds: form.assetIds.filter((a: string) => a !== id),
                      })
                    }
                  >
                    Bỏ
                  </button>
                </div>
              ))}
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
        </Modal>
      )}
    </>
  );
}

function Offers() {
  const { data } = useData("/admin/offers"),
    { data: products } = useData("/admin/products"),
    { data: groups } = useData("/admin/config/groups");
  const { mutate, notify, online } = useApp();
  const [form, setForm] = useState<Row | null>(null),
    [stock, setStock] = useState<Row | null>(null),
    [delta, setDelta] = useState(""),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false);
  const edit = (o?: Row) =>
    setForm(
      o
        ? {
            ...o,
            prices: groups.map((g: Row) => ({
              groupId: g.id,
              unitPrice:
                o.prices.find((p: Row) => p.group_id === g.id)?.unit_price ??
                "",
              expectedVersion: String(
                o.prices.find((p: Row) => p.group_id === g.id)?.version ?? "",
              ),
            })),
          }
        : {
            productId: products?.[0]?.id,
            batchCode: "DOT-" + new Date().toISOString().slice(0, 10),
            opensAt: new Date().toISOString().slice(0, 16),
            closesAt: new Date(Date.now() + 86400000)
              .toISOString()
              .slice(0, 16),
            availableQty: "0",
            status: "DRAFT",
            prices:
              groups?.map((g: Row) => ({
                groupId: g.id,
                unitPrice: "",
                expectedVersion: "",
              })) ?? [],
          },
    );
  return (
    <>
      <Heading
        title="Đợt mở bán"
        sub="Mở hàng theo đợt, đặt giá cho từng nhóm và theo dõi nhu cầu đang chờ."
      >
        <button
          className="primary"
          disabled={!online || !groups || !products}
          onClick={() => edit()}
        >
          <Icon icon={faPlus} /> Mở đợt mới
        </button>
      </Heading>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Mặt hàng / đợt</th>
              <th>Còn kho</th>
              <th>Nhu cầu chờ</th>
              <th>Giá theo nhóm</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.map((o: Row) => (
              <tr key={o.id}>
                <td>
                  <strong>{o.name}</strong>
                  <div className="product-subtitle">
                    {o.batch_code} · {o.sale_date}
                  </div>
                </td>
                <td>
                  {qty(o.available_qty)} {o.unit}
                </td>
                <td>
                  {qty(o.pending_qty)} {o.unit}
                  <div className="product-subtitle">
                    {o.pending_customers} khách chờ · {o.approved_orders} đơn đã
                    duyệt
                  </div>
                </td>
                <td>
                  {o.prices.map((p: Row) => (
                    <div key={p.group_id}>
                      <small>
                        {groups?.find((g: Row) => g.id === p.group_id)?.name}
                        :{" "}
                      </small>
                      {money(p.unit_price)}
                    </div>
                  ))}
                </td>
                <td>
                  <Status value={o.status} />
                  {o.processing_locked_at && (
                    <div className="status LOCKED">Khóa xử lý</div>
                  )}
                </td>
                <td>
                  <div className="actions">
                    <button
                      className="small"
                      onClick={() => edit(o)}
                      disabled={!groups}
                    >
                      Sửa đợt / giá
                    </button>
                    <button
                      className="small"
                      onClick={() => {
                        setStock(o);
                        setDelta("");
                        setReason("");
                      }}
                    >
                      Điều chỉnh kho
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {form && (
        <Modal
          title={form.id ? "Cập nhật đợt và giá" : "Tạo đợt mở bán"}
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
                  prices: form.prices.filter((p: Row) => p.unitPrice !== ""),
                };
                if (!form.id) {
                  b.opensAt = form.opensAt + ":00Z";
                  b.closesAt = form.closesAt + ":00Z";
                }
                await mutate(
                  "/admin/offers" + (form.id ? "/" + form.id : ""),
                  b,
                  form.id ? "PATCH" : "POST",
                );
                setForm(null);
                notify("Đã lưu đợt bán và giá nhóm");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            {!form.id && (
              <>
                <Field label="Sản phẩm" wide>
                  <select
                    required
                    value={form.productId ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, productId: e.target.value })
                    }
                  >
                    {products
                      ?.filter((p: Row) => p.active)
                      .map((p: Row) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field label="Mã đợt">
                  <input
                    required
                    maxLength={64}
                    value={form.batchCode}
                    onChange={(e) =>
                      setForm({ ...form, batchCode: e.target.value })
                    }
                  />
                </Field>
                <Field label="Kho ban đầu">
                  <input
                    required
                    type="number"
                    min="0"
                    step=".001"
                    value={form.availableQty}
                    onChange={(e) =>
                      setForm({ ...form, availableQty: e.target.value })
                    }
                  />
                </Field>
                <Field label="Mở lúc (UTC)">
                  <input
                    required
                    type="datetime-local"
                    value={form.opensAt}
                    onChange={(e) =>
                      setForm({ ...form, opensAt: e.target.value })
                    }
                  />
                </Field>
                <Field label="Đóng lúc (UTC)">
                  <input
                    required
                    type="datetime-local"
                    value={form.closesAt}
                    onChange={(e) =>
                      setForm({ ...form, closesAt: e.target.value })
                    }
                  />
                </Field>
              </>
            )}
            <Field label="Trạng thái">
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
              >
                {["DRAFT", "OPEN", "CLOSED"].map((s) => (
                  <option key={s} value={s}>
                    {statuses[s]}
                  </option>
                ))}
              </select>
            </Field>
            {form.id && (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={form.processingLocked ?? !!form.processing_locked_at}
                  onChange={(e) =>
                    setForm({ ...form, processingLocked: e.target.checked })
                  }
                />
                Khóa duyệt đợt này
              </label>
            )}
            {form.prices.map((p: Row, index: number) => (
              <Field
                key={p.groupId}
                label={
                  "Giá (đ) · " +
                  groups?.find((g: Row) => g.id === p.groupId)?.name
                }
              >
                <input
                  type="number"
                  min="0"
                  step="1"
                  required={form.status === "OPEN"}
                  value={p.unitPrice}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      prices: form.prices.map((x: Row, i: number) =>
                        i === index ? { ...x, unitPrice: e.target.value } : x,
                      ),
                    })
                  }
                />
              </Field>
            ))}
            <button className="primary" disabled={!online || busy}>
              Lưu đợt bán
            </button>
          </form>
        </Modal>
      )}
      {stock && (
        <Modal
          title={"Điều chỉnh kho · " + stock.name}
          close={() => setStock(null)}
        >
          <p>
            Còn trong kho:{" "}
            <strong>
              {qty(stock.available_qty)} {stock.unit}
            </strong>
          </p>
          <form
            className="form"
            style={{ marginTop: 18 }}
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                await mutate("/admin/inventory-adjustments", {
                  offerId: stock.id,
                  expectedVersion: String(stock.version),
                  delta,
                  reason,
                });
                setStock(null);
                notify("Đã điều chỉnh kho và lưu lịch sử");
              } catch {
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Lượng tăng (+) / giảm (−)">
              <input
                required
                type="number"
                step=".001"
                value={delta}
                onChange={(e) => setDelta(e.target.value)}
              />
            </Field>
            <Field label="Lý do (bắt buộc)">
              <textarea
                required
                minLength={3}
                maxLength={1000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </Field>
            <button className="primary" disabled={!online || busy}>
              Xác nhận điều chỉnh
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

function Users() {
  const [page, setPage] = useState(0);
  const { data } = useData("/admin/users?page=" + page),
    { data: groups } = useData("/admin/config/groups");
  const { mutate, notify, session, online } = useApp();
  const [selected, setSelected] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  return (
    <>
      <Heading
        title="Khách hàng"
        sub="Phân nhóm giá, khóa và mở tài khoản. Mọi thay đổi đều được ghi lịch sử."
      />
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Họ tên</th>
              <th>Liên hệ</th>
              <th>Nhóm giá</th>
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
                    {u.role === "ADMIN" ? "Quản trị viên" : "Khách hàng"}
                  </div>
                </td>
                <td>
                  {u.phone_e164}
                  <div className="muted">{u.email_normalized}</div>
                </td>
                <td>{groups?.find((g: Row) => g.id === u.group_id)?.name}</td>
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
            <Field label="Nhóm giá">
              <select
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
              </select>
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
    title: "Nhóm giá",
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
  zones: {
    title: "Khu giao",
    fields: [
      ["code", "Mã khu", "text"],
      ["name", "Tên khu vực", "text"],
      ["description", "Mô tả", "text"],
    ],
  },
  policies: {
    title: "Chính sách giao",
    fields: [
      ["groupId", "Nhóm giá", "select", "groups"],
      ["zoneId", "Khu giao", "select", "zones"],
      ["method", "Cách giao", "select", "methods"],
      ["minimumSubtotal", "Tiền hàng tối thiểu (đ)", "number"],
      ["shippingFee", "Phí giao (đ)", "number"],
    ],
  },
  "pickup-slots": {
    title: "Điểm / giờ giao",
    fields: [
      ["zoneId", "Khu giao", "select", "zones"],
      ["name", "Tên điểm và khung giờ", "text"],
      ["addressLine", "Địa chỉ nhận tập trung", "text"],
      ["startsAt", "Bắt đầu (UTC)", "datetime-local"],
      ["endsAt", "Kết thúc (UTC)", "datetime-local"],
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
  const [kind, setKind] = useState("policies"),
    [form, setForm] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const { data } = useData("/admin/config/" + kind),
    { data: groups } = useData("/admin/config/groups"),
    { data: zones } = useData("/admin/config/zones");
  const { mutate, online, notify } = useApp();
  const spec = configSpecs[kind];
  const options: Record<string, Row[]> = {
    groups: groups ?? [],
    zones: zones ?? [],
    methods: [
      { id: "INDIVIDUAL", name: "Giao riêng" },
      { id: "COLLECTIVE", name: "Tập trung sinh viên" },
    ],
    matchModes: [
      { id: "TOKEN", name: "Từ nguyên vẹn" },
      { id: "PHRASE", name: "Cụm từ" },
    ],
  };
  const edit = (row?: Row) => {
    const f: Row = {
      id: row?.id,
      version: row?.version,
      active: row?.active ?? true,
    };
    for (const [key, , type, source] of spec.fields) {
      let v = row?.[key === "phrase" ? "phrase_normalized" : snake(key)];
      if (type === "datetime-local" && v) v = v.slice(0, 16);
      f[key] =
        v ??
        (type === "select"
          ? options[source!]?.[0]?.id
          : type === "number"
            ? "0"
            : "");
    }
    setForm(f);
  };
  return (
    <>
      <Heading
        title="Cấu hình vận hành"
        sub="Quản lý nhóm, chính sách giao, danh mục và kiểm duyệt nội dung."
      />
      <div className="tabs">
        {Object.entries(configSpecs).map(([id, s]) => (
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
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              {spec.fields.map(([key, label]) => (
                <th key={key}>{label}</th>
              ))}
              <th>Hiệu lực</th>
              <th />
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
                          : String(value ?? "")}
                    </td>
                  );
                })}
                <td>{row.active === false ? "Tắt" : "Đang dùng"}</td>
                <td>
                  <button className="small" onClick={() => edit(row)}>
                    Sửa
                  </button>
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
            {spec.fields.map(([key, label, type, source]) => (
              <Field key={key} label={label}>
                {type === "select" ? (
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
                    required={key !== "description"}
                    type={type}
                    min={type === "number" ? "0" : undefined}
                    step={type === "number" ? "1" : undefined}
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

function Reports() {
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const start = month + "-01T00:00:00Z";
  const d = new Date(start);
  d.setUTCMonth(d.getUTCMonth() + 1);
  const end = Number.isNaN(d.getTime())
    ? "2026-11-01T00:00:00Z"
    : d.toISOString();
  const { data } = useData(
    "/admin/reports?start=" +
      encodeURIComponent(start) +
      "&end=" +
      encodeURIComponent(end),
  );
  const totals = (data?.daily ?? []).reduce(
    (t: Row, r: Row) => ({
      orders: t.orders + Number(r.orders),
      merchandise: t.merchandise + BigInt(String(r.merchandise)),
      shipping: t.shipping + BigInt(String(r.shipping)),
    }),
    { orders: 0, merchandise: BigInt(0), shipping: BigInt(0) },
  );
  return (
    <>
      <Heading
        title="Báo cáo bán hàng"
        sub="Ghi nhận tiền hàng và phí giao của đơn đã giao thành công. Không tính đơn chờ hoặc đã hủy."
      />
      <div className="toolbar">
        <Field label="Tháng báo cáo">
          <input
            type="month"
            required
            value={month}
            onChange={(e) => {
              if (e.target.value) setMonth(e.target.value);
            }}
          />
        </Field>
        <button
          onClick={() => {
            const blob = new Blob(
              [
                "\uFEFFNgày,Đơn đã giao,Tiền hàng,Phí giao\n" +
                  (data?.daily ?? [])
                    .map((r: Row) =>
                      [r.day, r.orders, r.merchandise, r.shipping].join(","),
                    )
                    .join("\n"),
              ],
              { type: "text/csv;charset=utf-8" },
            );
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "bao-cao-" + month + ".csv";
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          Xuất CSV
        </button>
      </div>
      <div className="report-totals">
        <div>
          <p className="muted">Đơn đã giao</p>
          <div className="report-value">{totals.orders}</div>
        </div>
        <div>
          <p className="muted">Doanh thu hàng</p>
          <div className="report-value">{money(totals.merchandise)}</div>
        </div>
        <div>
          <p className="muted">Phí giao ghi nhận</p>
          <div className="report-value">{money(totals.shipping)}</div>
        </div>
      </div>
      <div className="panel">
        <div className="panel-head">
          <h2>Theo ngày</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ngày</th>
                <th>Đơn đã giao</th>
                <th>Tiền hàng</th>
                <th>Phí giao</th>
              </tr>
            </thead>
            <tbody>
              {data?.daily.map((r: Row) => (
                <tr key={r.day}>
                  <td>{r.day}</td>
                  <td>{r.orders}</td>
                  <td>{money(r.merchandise)}</td>
                  <td>{money(r.shipping)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data?.daily.length && (
          <Empty title="Chưa có đơn giao thành công trong tháng" />
        )}
      </div>
      <h2 style={{ margin: "24px 0 12px" }}>Hàng đã bán</h2>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Mặt hàng</th>
              <th>Số lượng</th>
              <th>Doanh thu</th>
            </tr>
          </thead>
          <tbody>
            {data?.sold.map((r: Row) => (
              <tr key={r.name + r.unit}>
                <td>{r.name}</td>
                <td>
                  {qty(r.quantity)} {r.unit}
                </td>
                <td>{money(r.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="footer-note">
        Khoảng thời gian được tổng hợp theo UTC. Trạng thái đơn tạo trong tháng:{" "}
        {data?.states
          .map((r: Row) => `${statuses[r.status]}: ${r.count}`)
          .join(" · ")}
      </p>
    </>
  );
}

function Audit() {
  const [kind, setKind] = useState("audit");
  const { data } = useData(
    "/admin/" + (kind === "violations" ? "moderation/violations" : kind),
  );
  return (
    <>
      <Heading
        title="Nhật ký vận hành"
        sub="Truy vết thay đổi, điều chỉnh kho và vi phạm nội dung. Chỉ quản trị được xem."
      />
      <div className="tabs">
        {[
          ["audit", "Thao tác quản trị"],
          ["inventory-movements", "Biến động kho"],
          ["violations", "Vi phạm nội dung"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={id === kind ? "active" : ""}
            onClick={() => setKind(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="panel table-scroll" style={{ marginTop: 18 }}>
        <table>
          <thead>
            <tr>
              <th>Thời điểm</th>
              <th>Hoạt động</th>
              <th>Tham chiếu</th>
              <th>Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((r: Row) => (
              <tr key={r.id}>
                <td className="date">{date(r.created_at)}</td>
                <td>{r.action ?? r.kind ?? r.field_name}</td>
                <td>
                  {(r.entity_id ?? r.order_id ?? r.reference_id ?? "").slice(
                    0,
                    8,
                  )}
                </td>
                <td style={{ maxWidth: 450, overflowWrap: "anywhere" }}>
                  {kind === "violations" ? (
                    <>
                      <span>{r.original_restricted}</span> → {r.sanitized}
                    </>
                  ) : kind === "inventory-movements" ? (
                    <>
                      {qty(r.quantity_delta)} · Sau thay đổi:{" "}
                      {qty(r.balance_after)}
                      <p>{r.reason}</p>
                    </>
                  ) : (
                    <>
                      <small>Trước: {JSON.stringify(r.before_data)}</small>
                      <p>Sau: {JSON.stringify(r.after_data)}</p>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.length === 0 && <Empty title="Chưa có bản ghi" />}
      </div>
    </>
  );
}
