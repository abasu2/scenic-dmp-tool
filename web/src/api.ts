import type { ErrorInfo, MapData, Patch, Scene, ServerMessage, ViewSpec } from "./types";

export class ApiError extends Error {
  constructor(
    public info: ErrorInfo,
    public status: number,
  ) {
    super(info.message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError({ message: "can't reach the scenic-dmp server", where: "network" }, 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const info: ErrorInfo = data?.error ?? { message: data?.detail ? JSON.stringify(data.detail) : res.statusText };
    throw new ApiError(info, res.status);
  }
  return data as T;
}

export type ScenesSource = "mu" | "muprime" | "pprime";

export const api = {
  setProgram: (body: { source?: string; mode2D?: boolean; path?: string | null }) =>
    call<{ dirty: boolean }>("POST", "/api/program", body),
  openProgram: (path: string, mode2D?: boolean) => call("POST", "/api/program/open", { path, mode2D }),
  setViews: (views: ViewSpec[], f: string | null, preview: string | null) =>
    call<{ resampling: boolean; views: ViewSpec[]; f: string | null; preview: string | null }>("POST", "/api/views", {
      views,
      f,
      preview,
    }),
  detect: (spec: ViewSpec) =>
    call<{ values?: string[] | null; numeric?: boolean; min?: number; max?: number; too_many?: boolean }>(
      "POST",
      "/api/views/detect",
      { spec },
    ),
  setPreview: (name: string) => call("POST", "/api/preview", { name }),
  sample: (n: number, fresh: boolean, seed?: number) => call("POST", "/api/sample", { n, fresh, seed }),
  stop: () => call("POST", "/api/stop"),
  setNu: (nu: number[]) => call("PUT", "/api/nu", { nu }),
  resetNu: () => call("POST", "/api/nu/reset"),
  uniformNu: () => call("POST", "/api/nu/uniform"),
  patch: () => call<Patch>("GET", "/api/patch"),
  previewPatch: (nu: number[]) => call<Patch>("POST", "/api/patch/preview", { nu }),
  validate: (n: number) => call("POST", "/api/validate", { n }),
  scenes: (q: { source: ScenesSource; view?: string; value?: number; count: number; seed: number }) => {
    const params = new URLSearchParams({ source: q.source, count: String(q.count), seed: String(q.seed) });
    if (q.view !== undefined) params.set("view", q.view);
    if (q.value !== undefined) params.set("value", String(q.value));
    return call<{ total: number; scenes: Scene[] }>("GET", `/api/scenes?${params}`);
  },
  map: () => call<{ map: MapData | null }>("GET", "/api/map"),
  workspace: () => call<unknown>("GET", "/api/workspace"),
  saveWorkspace: (path: string) => call<{ path: string }>("POST", "/api/workspace/save", { path }),
  loadWorkspace: (body: { path: string } | { workspace: unknown }) => call("POST", "/api/workspace/load", body),
};

/** A WebSocket to the server that reconnects; returns a function that closes it. */
export function connect(onMessage: (msg: ServerMessage) => void, onStatus: (connected: boolean) => void) {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => onStatus(true);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onclose = () => {
      onStatus(false);
      if (!closed) retry = setTimeout(open, 1000);
    };
  };
  open();
  return () => {
    closed = true;
    clearTimeout(retry);
    ws?.close();
  };
}
