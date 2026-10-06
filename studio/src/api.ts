let executor: string | null = null;
export function setApiExecutor(value: string | null) {
  executor = value;
}
export function apiUrl(path: string): string {
  return executor
    ? `/api/executors/${encodeURIComponent(executor)}/proxy${path}`
    : `/api${path}`;
}
export function api<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(apiUrl(path), init);
}
export function relayApi<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`/api${path}`, init);
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const raw = await response.text();
    let message = raw || response.statusText;
    try {
      const body = JSON.parse(raw);
      message =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail || body.error || body);
    } catch {
      /* Keep plain diagnostic text. */
    }
    if (response.status === 401 || response.status === 403) {
      message =
        import.meta.env.MODE === "cloud"
          ? "Studio access was denied. Reload to sign in again, or ask the workspace owner to check the deployment settings."
          : "This Studio session has expired. Reopen Studio from the Parallax plugin to reconnect.";
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
