import type { ResearchOutcome, ResearchSnapshot, ResearchStatus, ResearchStreamEvent, ResearchSummary } from "./api";

export interface SourceItem { title: string; url: string; snippet: string; raw: string }
export interface ToolCallLog {
  eventId: number; agent: string; tool: string; parameters: Record<string, unknown>;
  result: string; noteId: string | null; notePath: string | null; timestamp: number;
}
export interface TodoTaskView {
  id: number; title: string; intent: string; query: string; status: string;
  summary: string; sourcesSummary: string; sourceItems: SourceItem[]; notices: string[];
  noteId: string | null; notePath: string | null; toolCalls: ToolCallLog[];
}
export interface ResearchSession {
  id: string; topic: string; status: ResearchStatus; createdAt: string;
  lastSeq: number; tasks: TodoTaskView[]; report: string; logs: string[];
  outcome: ResearchOutcome | null; notice: string;
  connection: "connecting" | "live" | "offline" | "ended" | "missing";
  connectionError: string;
  activeTaskId: number | null; resultView: "tasks" | "report";
  detailView: "sources" | "summary" | "tools"; logsCollapsed: boolean;
}
export const isResearchActive = (status: string) => ["PENDING", "RUNNING", "CANCELLING"].includes(status);
export const STATUS_LABEL: Record<string, string> = {
  PENDING: "排队中", RUNNING: "进行中", CANCELLING: "取消中", COMPLETED: "已完成",
  PARTIAL: "部分完成", FAILED: "失败", CANCELLED: "已取消"
};
export const text = (value: unknown): string => typeof value === "string" ? value : "";
const optional = (value: unknown) => text(value).trim() || null;
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

export function createSession(item: ResearchSummary): ResearchSession {
  return { id: item.research_id, topic: item.topic, status: item.status, createdAt: item.created_at,
    lastSeq: 0, tasks: [], report: "", logs: [], outcome: null, notice: "",
    connection: "connecting", connectionError: "", activeTaskId: null,
    resultView: "tasks", detailView: "summary", logsCollapsed: false };
}

function noteMetadata(task: TodoTaskView, payload: Record<string, unknown>) {
  if (optional(payload.note_id)) task.noteId = optional(payload.note_id);
  if (optional(payload.note_path)) task.notePath = optional(payload.note_path);
}
function taskFrom(item: Record<string, unknown>, topic: string, index: number): TodoTaskView {
  const id = Number(item.id ?? index + 1);
  const sourcesSummary = text(item.sources_summary);
  return { id, title: text(item.title) || `任务${id}`, intent: text(item.intent), query: text(item.query) || topic,
    status: text(item.status) || "pending", summary: text(item.summary), sourcesSummary,
    sourceItems: parseSources(sourcesSummary), notices: Array.isArray(item.notices) ? item.notices.map(String) : [],
    noteId: optional(item.note_id), notePath: optional(item.note_path), toolCalls: [] };
}
function toolFrom(event: ResearchStreamEvent): ToolCallLog {
  return { eventId: Number(event.event_id ?? event.seq), agent: text(event.agent) || "Agent",
    tool: text(event.tool) || "tool", parameters: record(event.parameters), result: text(event.result),
    noteId: optional(event.note_id), notePath: optional(event.note_path),
    timestamp: event.timestamp ? Date.parse(event.timestamp) : Date.now() };
}
function logFrom(event: ResearchStreamEvent): string {
  if (event.type === "status") return text(event.message);
  if (event.type === "research_status") return `研究状态：${STATUS_LABEL[text(event.status)] || text(event.status)}`;
  if (event.type === "task_status") {
    const status: Record<string, string> = { in_progress: "开始执行", completed: "完成", skipped: "跳过", failed: "失败", cancelled: "取消" };
    return `任务 ${event.task_id}：${status[text(event.status)] || text(event.status)}${event.detail ? `，${event.detail}` : ""}`;
  }
  if (event.type === "tool_call") return `${text(event.agent) || "Agent"} 调用了 ${text(event.tool)}${event.task_id ? `（任务 ${event.task_id}）` : ""}`;
  return "";
}
function outcomeNotice(outcome: ResearchOutcome | null): string {
  if (!outcome) return "";
  if (outcome.error) return outcome.error;
  if (outcome.status === "partial") return `研究部分完成：成功 ${outcome.completed_tasks}/${outcome.total_tasks}，失败 ${outcome.failed_tasks}，跳过 ${outcome.skipped_tasks}。`;
  if (outcome.status === "failed") return "研究未成功完成。";
  if (outcome.status === "cancelled") return "后台已确认研究取消。";
  return "";
}

export function applySnapshot(session: ResearchSession, snapshot: ResearchSnapshot): boolean {
  if (snapshot.research_id !== session.id || snapshot.snapshot_seq < session.lastSeq) return false;
  session.topic = snapshot.topic;
  session.status = snapshot.status;
  session.createdAt = snapshot.created_at;
  session.tasks = snapshot.todo_items.map((item, index) => taskFrom(item, session.topic, index));
  for (const event of snapshot.tool_calls) {
    const task = session.tasks.find(task => task.id === Number(event.task_id));
    if (task) task.toolCalls.push(toolFrom(event));
  }
  session.report = snapshot.report_markdown;
  session.logs = [...snapshot.logs, ...snapshot.tool_calls].sort((a, b) => Number(a.seq) - Number(b.seq))
    .map(logFrom).filter(Boolean);
  session.outcome = snapshot.outcome;
  session.notice = outcomeNotice(snapshot.outcome);
  session.lastSeq = snapshot.snapshot_seq;
  if (!session.tasks.some(task => task.id === session.activeTaskId)) session.activeTaskId = session.tasks[0]?.id ?? null;
  return true;
}

export function applyResearchEvent(session: ResearchSession, event: ResearchStreamEvent): boolean {
  if (event.research_id !== session.id || !Number.isInteger(event.seq) || Number(event.seq) <= session.lastSeq) return false;
  if (Number(event.seq) !== session.lastSeq + 1) throw new Error("事件序号不连续，需要重新同步研究快照");
  const task = session.tasks.find(task => task.id === Number(event.task_id));
  if (event.type === "research_status") session.status = text(event.status) as ResearchStatus;
  if (event.type === "todo_list") {
    session.tasks = (Array.isArray(event.tasks) ? event.tasks : []).map((item, index) => taskFrom(record(item), session.topic, index));
    if (!session.tasks.some(task => task.id === session.activeTaskId)) session.activeTaskId = session.tasks[0]?.id ?? null;
  }
  if (task) {
    noteMetadata(task, event);
    if (event.type === "status" && event.message) task.notices.push(text(event.message));
    if (event.type === "task_status") {
      for (const key of ["title", "intent", "query"] as const) if (text(event[key])) task[key] = text(event[key]);
      task.status = text(event.status) || task.status;
      if (typeof event.summary === "string") task.summary = event.summary;
      if (typeof event.sources_summary === "string") {
        task.sourcesSummary = event.sources_summary;
        task.sourceItems = parseSources(task.sourcesSummary);
      }
      if (event.detail) task.notices.push(text(event.detail));
    }
    if (event.type === "task_summary_chunk") task.summary += text(event.content);
    if (event.type === "sources") {
      task.sourcesSummary = text(event.latest_sources) || text(event.sources_summary) || text(event.raw_context);
      task.sourceItems = parseSources(task.sourcesSummary);
    }
    if (event.type === "tool_call") task.toolCalls.push(toolFrom(event));
  }
  if (event.type === "final_report") session.report = text(event.report);
  if (event.type === "done") {
    session.outcome = event.outcome || null;
    if (session.outcome) session.status = session.outcome.status.toUpperCase() as ResearchStatus;
    session.notice = outcomeNotice(session.outcome);
    session.connection = "ended";
  }
  if (event.type === "error") session.notice = text(event.detail) || "研究发生异常，请重新同步状态";
  const log = logFrom(event);
  if (log) session.logs.push(log);
  session.lastSeq = Number(event.seq);
  return true;
}

export function parseSources(raw: string): SourceItem[] {
  if (!raw) {
    return [];
  }

  const items: SourceItem[] = [];
  const lines = raw.split("\n");

  let current: SourceItem | null = null;
  const truncate = (value: string, max = 360) => {
    const trimmed = value.trim();
    return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
  };

  const flush = () => {
    if (!current) {
      return;
    }
    const normalized: SourceItem = {
      title: current.title?.trim() || "",
      url: current.url?.trim() || "",
      snippet: current.snippet ? truncate(current.snippet) : "",
      raw: current.raw ? truncate(current.raw, 420) : ""
    };

    if (
      normalized.title ||
      normalized.url ||
      normalized.snippet ||
      normalized.raw
    ) {
      if (!normalized.title && normalized.url) {
        normalized.title = normalized.url;
      }
      items.push(normalized);
    }
    current = null;
  };

  const ensureCurrent = () => {
    if (!current) {
      current = { title: "", url: "", snippet: "", raw: "" };
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    if (/^\*/.test(trimmed) && trimmed.includes(" : ")) {
      flush();
      const withoutBullet = trimmed.replace(/^\*\s*/, "");
      const [titlePart, urlPart] = withoutBullet.split(" : ");
      current = {
        title: titlePart?.trim() || "",
        url: urlPart?.trim() || "",
        snippet: "",
        raw: ""
      };
      continue;
    }

    if (/^(Source|信息来源)\s*:/.test(trimmed)) {
      flush();
      const [, titlePart = ""] = trimmed.split(/:\s*(.+)/);
      current = {
        title: titlePart.trim(),
        url: "",
        snippet: "",
        raw: ""
      };
      continue;
    }

    if (/^URL\s*:/.test(trimmed)) {
      ensureCurrent();
      const [, urlPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.url = urlPart.trim();
      continue;
    }

    if (
      /^(Most relevant content from source|信息内容)\s*:/.test(trimmed)
    ) {
      ensureCurrent();
      const [, contentPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.snippet = contentPart.trim();
      continue;
    }

    if (
      /^(Full source content limited to|信息内容限制为)\s*:/.test(trimmed)
    ) {
      ensureCurrent();
      const [, rawPart = ""] = trimmed.split(/:\s*(.+)/);
      current!.raw = rawPart.trim();
      continue;
    }

    if (/^https?:\/\//.test(trimmed)) {
      ensureCurrent();
      if (!current!.url) {
        current!.url = trimmed;
        continue;
      }
    }

    ensureCurrent();
    current!.raw = current!.raw ? `${current!.raw}\n${trimmed}` : trimmed;
  }

  flush();
  return items;
}

