/**
 * The one way the SPA talks to the server: `api.get/post/patch/put/delete`.
 *
 * - Same-origin JSON with the session cookie (`credentials: "same-origin"`).
 * - `X-Timezone` (the browser's IANA zone) on every request: the server dates
 *   saves and retirements in the viewer's day (web/viewer_zone.py).
 * - `X-Requested-With: sensibility` on every mutation: the server refuses a
 *   mutating /api/ request without it (403), which is the CSRF defense
 *   (web/csrf.py).
 * - A non-2xx answer throws `ApiError` carrying the server's `{"error": …}`
 *   message, ready to show the user.
 * - Any 401 means the session is gone: full navigation to `/login`.
 */

export const CSRF_HEADER = "X-Requested-With";
export const CSRF_VALUE = "sensibility";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type Query = Record<
  string,
  string | number | boolean | null | undefined
>;

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

/** The viewer's IANA time zone, or undefined if the browser won't say. */
export function viewerZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** Where a 401 sends the browser. A seam for tests. */
export const session = {
  expired() {
    window.location.assign("/login");
  },
};

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function request<T>(
  method: Method,
  path: string,
  { query, body, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const zone = viewerZone();
  if (zone) headers["X-Timezone"] = zone;
  if (method !== "GET") headers[CSRF_HEADER] = CSRF_VALUE;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(withQuery(path, query), {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (response.status === 401) {
    session.expired();
    throw new ApiError(401, "Login required");
  }
  const text = await response.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = undefined;
    }
  }
  if (!response.ok) {
    const message =
      data && typeof data === "object" && "error" in data
        ? String((data as { error: unknown }).error)
        : `Request failed (${response.status})`;
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) =>
    request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>("DELETE", path, options),
};
