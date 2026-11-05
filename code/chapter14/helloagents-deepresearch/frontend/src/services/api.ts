const baseURL = import.meta.env?.VITE_API_BASE_URL || "http://localhost:8000";

export interface ResearchRequest {
  topic: string;
  search_api?: string;
}

export type ResearchStatus = "PENDING" | "RUNNING" | "CANCELLING" | "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED" | "INTERRUPTED";

export interface ResearchOutcome {
  status: "completed" | "partial" | "failed" | "cancelled" | "interrupted";
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  skipped_tasks: number;
  cancelled_tasks: number;
  interrupted_tasks?: number;
  report_available: boolean;
  error: string | null;
}

export interface ResearchSummary {
  research_id: string;
  topic: string;
  status: ResearchStatus;
  stage: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  snapshot_seq: number;
  event_epoch?: string;
  history_only?: boolean;
  persistence_error?: string | null;
  report_available: boolean;
  error: string | null;
  progress: { total_tasks: number; completed_tasks: number };
}

export interface ResearchSnapshot extends ResearchSummary {
  todo_items: Record<string, unknown>[];
  report_markdown: string;
  outcome: ResearchOutcome | null;
  logs: ResearchStreamEvent[];
  tool_calls: ResearchStreamEvent[];
}

export interface ResearchStreamEvent {
  type: string;
  research_id?: string;
  seq?: number;
  timestamp?: string;
  event_epoch?: string;
  outcome?: ResearchOutcome;
  [key: string]: unknown;
}

export class ResearchAPIError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    let detail = `研究请求失败，状态码：${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* Keep a readable HTTP error if the response is not JSON. */ }
    throw new ResearchAPIError(response.status, detail);
  }
  return response;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await checked(await fetch(`${baseURL}${path}`, init))).json();
}

const pathFor = (id: string) => `/researches/${encodeURIComponent(id)}`;
export const listResearches = (signal?: AbortSignal) => request<{ researches: ResearchSummary[] }>("/researches", { signal });
export const getResearch = (id: string, signal?: AbortSignal) => request<ResearchSnapshot>(pathFor(id), { signal });
export const createResearch = (payload: ResearchRequest, signal?: AbortSignal) => request<ResearchSnapshot>("/researches", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal
});
export const cancelResearchById = (id: string, signal?: AbortSignal) => request<ResearchSnapshot>(`${pathFor(id)}/cancel`, {
  method: "POST", signal
});

export interface StreamOptions {
  signal?: AbortSignal;
  after?: number;
  onResearchId?: (researchId: string) => void;
}

async function readEvents(response: Response, onEvent: (event: ResearchStreamEvent) => void): Promise<void> {
  await checked(response);
  if (!response.body) throw new Error("浏览器不支持流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consume = (frame: string): boolean => {
    // SSE may contain id, comments, CRLF and multiple data lines.
    const data = frame.split("\n").filter(line => line.startsWith("data:"))
      .map(line => line.slice(5).replace(/^ /, "")).join("\n");
    if (!data) return false;
    const event = JSON.parse(data) as ResearchStreamEvent;
    onEvent(event);
    return event.type === "done";
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      // Normalize only complete CRLF pairs; a trailing CR can span reads.
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (consume(frame)) return;
      }
      if (done) {
        if (buffer.trim()) consume(buffer);
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function watchResearchEvents(id: string, onEvent: (event: ResearchStreamEvent) => void,
                                         options: StreamOptions = {}): Promise<void> {
  const response = await fetch(`${baseURL}${pathFor(id)}/events?after=${options.after || 0}`, {
    headers: { Accept: "text/event-stream" }, signal: options.signal
  });
  await readEvents(response, onEvent);
}

// Preserve the legacy helper for any other callers; M1 uses explicit registration.
export async function runResearchStream(payload: ResearchRequest, onEvent: (event: ResearchStreamEvent) => void,
                                        options: StreamOptions = {}): Promise<void> {
  const response = await checked(await fetch(`${baseURL}/research/stream`, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload), signal: options.signal
  }));
  const id = response.headers.get("X-Research-ID");
  if (id) options.onResearchId?.(id);
  await readEvents(response, onEvent);
}
