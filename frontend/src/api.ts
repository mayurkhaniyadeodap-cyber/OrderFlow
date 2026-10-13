/** Small fetch wrapper: adds the bearer token, normalises error messages, handles session expiry. */

const TOKEN_KEY = "orderflow.token";

export class ApiError extends Error {
  status: number;
  errors: string[];
  warnings: string[];
  code?: string;
  data?: Record<string, unknown>;

  constructor(status: number, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.errors = Array.isArray(extra.errors) ? (extra.errors as string[]) : [];
    this.warnings = Array.isArray(extra.warnings) ? (extra.warnings as string[]) : [];
    this.code = typeof extra.code === "string" ? extra.code : undefined;
    this.data = extra;
  }
}

// Session storage: closing the browser signs the user out (safer on shared computers).
export const tokenStore = {
  get: (): string | null => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string) => {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: token lives only in memory for this page */
    }
  },
  clear: () => {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

let onUnauthorized: ((message: string) => void) | null = null;
export function setUnauthorizedHandler(handler: (message: string) => void) {
  onUnauthorized = handler;
}

async function toError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(res.status, detail);
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>;
    return new ApiError(res.status, String(d.message ?? "Request failed."), d);
  }
  // OrderFlow always answers with a JSON "detail". Anything else came from a different program,
  // usually because the frontend proxy points at the wrong port.
  if (body === null && res.status !== 500 && res.status !== 502 && res.status !== 504) {
    return new ApiError(
      res.status,
      `Unexpected response (${res.status}) — this is not the OrderFlow backend. Another application may be using ` +
        "the backend port. Set PORT in backend\\.env (e.g. PORT=8010) and restart start_backend.bat and start_frontend.bat.",
    );
  }
  if (res.status === 502 || res.status === 504) {
    return new ApiError(res.status, "Cannot reach the OrderFlow backend. Check that start_backend.bat is running.");
  }
  const fallback: Record<number, string> = {
    403: "You do not have permission for this action.",
    404: "Not found.",
    413: "The file is too large.",
    500: "The server hit an unexpected error. Try again; if it persists, check the backend window.",
  };
  return new ApiError(res.status, fallback[res.status] ?? `Request failed (${res.status}).`);
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running (start_backend.bat).");
  }
  if (res.status === 401 && path !== "/api/login") {
    const err = await toError(res);
    tokenStore.clear();
    onUnauthorized?.(err.message);
    throw err;
  }
  if (!res.ok) throw await toError(res);
  return res;
}

export const api = {
  get: async <T>(path: string): Promise<T> => (await request(path)).json(),
  post: async <T>(path: string, body?: unknown): Promise<T> =>
    (await request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) })).json(),
  put: async <T>(path: string, body: unknown): Promise<T> =>
    (await request(path, { method: "PUT", body: JSON.stringify(body) })).json(),
  patch: async <T>(path: string, body: unknown): Promise<T> =>
    (await request(path, { method: "PATCH", body: JSON.stringify(body) })).json(),
  del: async <T>(path: string): Promise<T> => (await request(path, { method: "DELETE" })).json(),
  upload: async <T>(path: string, form: FormData): Promise<T> =>
    (await request(path, { method: "POST", body: form })).json(),
  blob: async (path: string): Promise<{ blob: Blob; filename: string | null }> => {
    const res = await request(path);
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const plain = /filename="?([^";]+)"?/i.exec(disposition);
    const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : null;
    return { blob: await res.blob(), filename };
  },
};

/** Open an authenticated file (PDF/image) in a new tab. */
export async function openFile(path: string) {
  const tab = window.open("", "_blank");
  try {
    const { blob } = await api.blob(path);
    const url = URL.createObjectURL(blob);
    if (tab) tab.location.href = url;
    else window.location.href = url;
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (err) {
    tab?.close();
    throw err;
  }
}

/** Download an authenticated file with the server-provided filename. */
export async function downloadFile(path: string, fallbackName: string) {
  const { blob, filename } = await api.blob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
