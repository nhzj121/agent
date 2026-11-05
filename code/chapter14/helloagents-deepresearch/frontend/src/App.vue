<template>
  <main class="app-shell" :class="{ expanded: isExpanded }">
    <div class="aurora" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
    </div>

    <!-- 初始状态：居中输入卡片 -->
    <div v-if="!isExpanded" class="layout layout-centered">
      <section class="panel panel-form panel-centered">
        <header class="panel-head">
          <div class="logo">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M12 2.5c-.7 0-1.4.2-2 .6L4.6 7C3.6 7.6 3 8.7 3 9.9v4.2c0 1.2.6 2.3 1.6 2.9l5.4 3.9c1.2.8 2.8.8 4 0l5.4-3.9c1-.7 1.6-1.7 1.6-2.9V9.9c0-1.2-.6-2.3-1.6-2.9L14 3.1a3.6 3.6 0 0 0-2-.6Z"
              />
            </svg>
          </div>
          <div>
            <h1>深度研究助手</h1>
            <p>结合多轮智能检索与总结，实时呈现洞见与引用。</p>
          </div>
        </header>

        <form class="form" @submit.prevent="handleSubmit">
          <label class="field">
            <span>研究主题</span>
            <textarea
              v-model="form.topic"
              placeholder="例如：探索多模态模型在 2025 年的关键突破"
              rows="4"
              required
            ></textarea>
          </label>

          <section class="options">
            <label class="field option">
              <span>搜索引擎</span>
              <select v-model="form.searchApi">
                <option value="">沿用后端配置</option>
                <option
                  v-for="option in searchOptions"
                  :key="option"
                  :value="option"
                >
                  {{ option }}
                </option>
              </select>
            </label>
          </section>

          <div class="form-actions">
            <button class="submit" type="submit" :disabled="submitting">
              <span class="submit-label">
                <svg
                  v-if="submitting"
                  class="spinner"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="9" stroke-width="3" />
                </svg>
                {{ submitting ? "正在提交…" : "开始研究" }}
              </span>
            </button>

          </div>
        </form>

        <p v-if="error" class="error-chip">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M10 3.2c-.3 0-.6.2-.8.5L3.4 15c-.4.7.1 1.6.8 1.6h11.6c.7 0 1.2-.9.8-1.6L10.8 3.7c-.2-.3-.5-.5-.8-.5Zm0 4.3c.4 0 .7.3.7.7v4c0 .4-.3.7-.7.7s-.7-.3-.7-.7V8.2c0-.4.3-.7.7-.7Zm0 6.6a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z"
            />
          </svg>
          {{ error }}
        </p>
        <p class="hint muted">可以连续提交多个主题，已有研究会继续在后台运行。</p>
        <ResearchList class="form-research-list" :items="researches" :selected-id="activeResearchId"
          :refreshing="refreshing" :error="listError" :cancelling="cancelling" :action-errors="actionErrors"
          @select="selectResearch" @cancel="cancelResearch" @refresh="refreshResearches" />
      </section>
    </div>

    <!-- 全屏状态：左右分栏布局 -->
    <div v-else class="layout layout-fullscreen">
      <!-- 左侧：研究信息 -->
      <aside class="sidebar">
        <div class="sidebar-header">
          <button class="back-btn" @click="goBack">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            返回
          </button>
          <h2>🔍 深度研究助手</h2>
        </div>

        <ResearchList :items="researches" :selected-id="activeResearchId" :refreshing="refreshing"
          :error="listError" :cancelling="cancelling" :action-errors="actionErrors"
          @select="selectResearch" @cancel="cancelResearch" @refresh="refreshResearches" />

        <div class="research-info">
          <details class="research-overview" open>
            <summary class="research-overview-heading">
              <span class="overview-label-row">
                <span class="overview-label">研究主题</span>
                <span class="disclosure-action disclosure-expand">展开 ＋</span>
                <span class="disclosure-action disclosure-collapse">收起 −</span>
              </span>
              <span class="topic-display">{{ selectedSession?.topic }}</span>
              <span class="status-chip" :class="{ active: loading, partial: researchStatus === 'partial', failed: researchStatus === 'failed' }">
                <span class="dot"></span>
                {{ researchStatusLabel }}
              </span>
            </summary>

            <div class="research-overview-body">
              <div class="info-item" v-if="totalTasks > 0">
                <label>研究进度</label>
                <div
                  class="progress-bar"
                  role="progressbar"
                  aria-label="研究任务完成进度"
                  :aria-valuenow="completedTasks"
                  :aria-valuemax="totalTasks"
                  aria-valuemin="0"
                >
                  <div class="progress-fill" :style="{ width: `${(completedTasks / totalTasks) * 100}%` }"></div>
                </div>
                <p class="progress-text">{{ completedTasks }} / {{ totalTasks }} 任务完成</p>
              </div>

              <p class="status-meta">研究流程阶段记录：{{ progressLogs.length }} 条</p>

              <div class="research-flow">
                <button
                  type="button"
                  class="flow-toggle"
                  :aria-expanded="!logsCollapsed"
                  aria-controls="research-flow-records"
                  @click="logsCollapsed = !logsCollapsed"
                >
                  <span>研究流程</span>
                  <span class="disclosure-action">{{ logsCollapsed ? "展开 ＋" : "收起 −" }}</span>
                </button>
                <div id="research-flow-records" v-show="!logsCollapsed">
                  <div class="timeline-wrapper" v-if="progressLogs.length">
                    <transition-group name="timeline" tag="ul" class="timeline">
                      <li v-for="(log, index) in progressLogs" :key="`${log}-${index}`">
                        <span class="timeline-node"></span>
                        <p>{{ log }}</p>
                      </li>
                    </transition-group>
                  </div>
                  <p v-else class="muted">暂无流程记录</p>
                </div>
              </div>
            </div>
          </details>
        </div>

        <div class="sidebar-actions">
          <button v-if="loading" class="secondary-btn" :disabled="cancelRequested" @click="cancelResearch(activeResearchId)">
            {{ cancelRequested ? '取消中…' : '取消当前研究' }}
          </button>
          <button class="new-research-btn" @click="startNewResearch">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
            </svg>
            开始新研究
          </button>
        </div>
      </aside>

      <!-- 右侧：研究结果 -->
      <section
        class="panel panel-result"
        v-if="selectedSession"
      >
        <p
          v-if="researchNotice"
          class="research-result-notice"
          :class="{ failed: researchStatus === 'failed' }"
          role="status"
        >{{ researchNotice }}</p>
        <p v-if="selectedSession?.connection === 'connecting'" class="hint muted" role="status">正在同步研究进展…</p>
        <button v-if="selectedSession && ['offline', 'missing'].includes(selectedSession.connection)" class="secondary-btn"
          @click="selectResearch(selectedSession.id)">重新同步当前研究</button>
        <nav class="result-tabs" aria-label="研究内容切换">
          <button
            type="button"
            class="view-tab"
            :aria-pressed="resultView === 'tasks'"
            aria-controls="research-tasks-view"
            @click="resultView = 'tasks'"
          >任务清单</button>
          <button
            type="button"
            class="view-tab"
            :aria-pressed="resultView === 'report'"
            aria-controls="research-report-view"
            @click="resultView = 'report'"
          >最终报告</button>
        </nav>

        <section id="research-tasks-view" v-show="resultView === 'tasks'" aria-label="研究任务">
          <div class="tasks-section" v-if="todoTasks.length">
            <nav class="tasks-list" aria-label="研究任务选择">
              <h3>任务清单</h3>
              <ul>
                <li
                  v-for="task in todoTasks"
                  :key="task.id"
                  :class="['task-item', { active: task.id === activeTaskId, completed: task.status === 'completed' }]"
                >
                  <button
                    type="button"
                    class="task-button"
                    :aria-pressed="task.id === activeTaskId"
                    @click="activeTaskId = task.id"
                  >
                    <span class="task-title">{{ task.title }}</span>
                    <span class="task-status" :class="task.status">
                      {{ formatTaskStatus(task.status) }}
                    </span>
                  </button>
                </li>
              </ul>
            </nav>

            <article class="task-detail" v-if="currentTask">
              <header class="task-header">
                <div>
                  <h3>{{ currentTaskTitle || "当前任务" }}</h3>
                  <p class="muted" v-if="currentTaskIntent">
                    {{ currentTaskIntent }}
                  </p>
                </div>
                <div class="task-chip-group">
                  <span class="task-label">查询：{{ currentTaskQuery || "" }}</span>
                </div>
              </header>

              <nav class="task-detail-tabs" aria-label="任务详情切换">
                <button
                  type="button"
                  class="view-tab"
                  :aria-pressed="taskDetailView === 'sources'"
                  aria-controls="task-sources-view"
                  @click="taskDetailView = 'sources'"
                >最新来源</button>
                <button
                  type="button"
                  class="view-tab"
                  :aria-pressed="taskDetailView === 'summary'"
                  aria-controls="task-summary-view"
                  @click="taskDetailView = 'summary'"
                >任务总结</button>
                <button
                  type="button"
                  class="view-tab"
                  :aria-pressed="taskDetailView === 'tools'"
                  aria-controls="task-tools-view"
                  @click="taskDetailView = 'tools'"
                >工具调用</button>
              </nav>

              <section v-if="currentTask && currentTask.notices.length" class="task-notices">
                <h4>系统提示</h4>
                <ul>
                  <li v-for="(notice, idx) in currentTask.notices" :key="`${notice}-${idx}`">
                    {{ notice }}
                  </li>
                </ul>
              </section>

              <section
                id="task-sources-view"
                v-show="taskDetailView === 'sources'"
                class="sources-block"
                :class="{ 'block-highlight': sourcesHighlight }"
              >
                <h3>最新来源</h3>
                <template v-if="currentTaskSources.length">
                  <ul class="sources-list">
                    <li
                      v-for="(item, index) in currentTaskSources"
                      :key="`${item.title}-${index}`"
                      class="source-item"
                    >
                      <a
                        class="source-link"
                        :href="item.url || '#'"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {{ item.title || item.url || `来源 ${index + 1}` }}
                      </a>
                      <div v-if="item.snippet || item.raw" class="source-tooltip">
                        <p v-if="item.snippet">{{ item.snippet }}</p>
                        <p v-if="item.raw" class="muted-text">{{ item.raw }}</p>
                      </div>
                    </li>
                  </ul>
                </template>
                <p v-else class="muted">暂无可用来源</p>
              </section>

              <section
                id="task-summary-view"
                v-show="taskDetailView === 'summary'"
                class="summary-block"
                :class="{ 'block-highlight': summaryHighlight }"
              >
                <h3>任务总结</h3>
                <MarkdownContent :content="currentTaskSummary || '暂无可用信息'" />
              </section>

              <section
                id="task-tools-view"
                v-show="taskDetailView === 'tools'"
                class="tools-block"
                :class="{ 'block-highlight': toolHighlight }"
              >
                <h3>工具调用记录</h3>
                <p v-if="!currentTaskToolCalls.length" class="muted">暂无工具调用记录</p>
                <ul class="tool-list" v-else>
                  <li
                    v-for="entry in currentTaskToolCalls"
                    :key="`${entry.eventId}-${entry.timestamp}`"
                    class="tool-entry"
                  >
                    <div class="tool-entry-header">
                      <span class="tool-entry-title">
                        #{{ entry.eventId }} {{ entry.agent }} → {{ entry.tool }}
                      </span>
                      <span
                        v-if="entry.noteId"
                        class="tool-entry-note"
                      >
                        笔记：{{ entry.noteId }}
                      </span>
                    </div>
                    <p v-if="entry.notePath" class="tool-entry-path">
                      笔记路径：
                      <button
                        class="link-btn"
                        type="button"
                        @click="copyNotePath(entry.notePath)"
                      >
                        复制
                      </button>
                      <span class="path-text">{{ entry.notePath }}</span>
                    </p>
                    <p class="tool-subtitle">参数</p>
                    <pre class="tool-pre">{{ formatToolParameters(entry.parameters) }}</pre>
                    <template v-if="entry.result">
                      <p class="tool-subtitle">执行结果</p>
                      <MarkdownContent :content="formatToolResult(entry.result)" />
                    </template>
                  </li>
                </ul>
              </section>
            </article>

            <article class="task-detail" v-else>
              <p class="muted">等待任务规划或执行结果。</p>
            </article>
          </div>

          <p v-else class="view-empty muted">等待任务规划或执行结果。</p>
        </section>

        <section id="research-report-view" v-show="resultView === 'report'" aria-label="研究最终报告">
          <div
            v-if="reportMarkdown"
            class="report-block"
            :class="{ 'block-highlight': reportHighlight }"
          >
            <h3>最终报告</h3>
            <MarkdownContent :content="reportMarkdown" />
          </div>
          <p v-else class="view-empty muted">{{ loading ? '等待最终报告生成。' : (researchStatus ? '本次未生成最终报告。' : '当前未收到最终报告。') }}</p>
        </section>
      </section>

    </div>
  </main>
</template>

<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import MarkdownContent from "./components/MarkdownContent.vue";
import ResearchList from "./components/ResearchList.vue";
import {
  createResearch, listResearches, getResearch, watchResearchEvents, cancelResearchById, ResearchAPIError,
  type ResearchSummary, type ResearchSnapshot, type ResearchOutcome
} from "./services/api";
import {
  createSession, applySnapshot, applyResearchEvent, isResearchActive, STATUS_LABEL,
  type ResearchSession
} from "./services/researchState";

const form = reactive({ topic: "", searchApi: "" });
const researches = ref<ResearchSummary[]>([]);
const sessions = reactive<Record<string, ResearchSession>>({});
const cancelling = reactive<Record<string, boolean>>({});
const actionErrors = reactive<Record<string, string>>({});
const activeResearchId = ref<string | null>(null);
const selectedSession = computed(() => activeResearchId.value ? sessions[activeResearchId.value] : undefined);
const submitting = ref(false);
const refreshing = ref(false);
const error = ref("");
const listError = ref("");
const isExpanded = ref(false);
const loading = computed(() => Boolean(selectedSession.value && selectedSession.value.connection !== "missing" && isResearchActive(selectedSession.value.status)));
const cancelRequested = computed(() => Boolean(activeResearchId.value && (cancelling[activeResearchId.value] || selectedSession.value?.status === "CANCELLING")));
const researchStatus = computed(() => {
  const status = selectedSession.value?.status;
  return status && !isResearchActive(status) ? status.toLowerCase() as ResearchOutcome["status"] : null;
});
const researchStatusLabel = computed(() => {
  if (selectedSession.value?.connection === "missing") return "研究记录已失效";
  return STATUS_LABEL[selectedSession.value?.status || ""] || "正在读取研究";
});
const researchNotice = computed(() => selectedSession.value?.connectionError || selectedSession.value?.notice || "");
const todoTasks = computed(() => selectedSession.value?.tasks || []);
const reportMarkdown = computed(() => selectedSession.value?.report || "");
const progressLogs = computed(() => selectedSession.value?.logs || []);
const activeTaskId = computed({
  get: () => selectedSession.value?.activeTaskId ?? null,
  set: (value: number | null) => { if (selectedSession.value) selectedSession.value.activeTaskId = value; }
});
const resultView = computed({
  get: () => selectedSession.value?.resultView || "tasks",
  set: (value: "tasks" | "report") => { if (selectedSession.value) selectedSession.value.resultView = value; }
});
const taskDetailView = computed({
  get: () => selectedSession.value?.detailView || "summary",
  set: (value: "sources" | "summary" | "tools") => { if (selectedSession.value) selectedSession.value.detailView = value; }
});
const logsCollapsed = computed({
  get: () => selectedSession.value?.logsCollapsed || false,
  set: (value: boolean) => { if (selectedSession.value) selectedSession.value.logsCollapsed = value; }
});
const totalTasks = computed(() => todoTasks.value.length);
const completedTasks = computed(() => todoTasks.value.filter(task => task.status === "completed").length);
const currentTask = computed(() => todoTasks.value.find(task => task.id === activeTaskId.value) || todoTasks.value[0] || null);
const currentTaskSources = computed(() => currentTask.value?.sourceItems || []);
const currentTaskSummary = computed(() => currentTask.value?.summary || "");
const currentTaskTitle = computed(() => currentTask.value?.title || "");
const currentTaskIntent = computed(() => currentTask.value?.intent || "");
const currentTaskQuery = computed(() => currentTask.value?.query || "");
const currentTaskNoteId = computed(() => currentTask.value?.noteId || "");
const currentTaskNotePath = computed(() => currentTask.value?.notePath || "");
const currentTaskToolCalls = computed(() => currentTask.value?.toolCalls || []);
const summaryHighlight = ref(false), sourcesHighlight = ref(false), reportHighlight = ref(false), toolHighlight = ref(false);
const searchOptions = ["advanced", "duckduckgo", "tavily", "perplexity", "searxng"];
const TASK_STATUS_LABEL: Record<string, string> = {
  pending: "待执行", in_progress: "进行中", completed: "已完成", skipped: "已跳过", failed: "失败", cancelled: "已取消"
};
const formatTaskStatus = (status: string) => TASK_STATUS_LABEL[status] || status;
function formatToolParameters(parameters: Record<string, unknown>): string {
  try { return JSON.stringify(parameters, null, 2); }
  catch (err) {
    console.warn("无法格式化工具参数", err, parameters);
    return Object.entries(parameters).map(([key, value]) => `${key}: ${String(value)}`).join("\n");
  }
}
function formatToolResult(result: string): string {
  const value = result.trim();
  return value.length > 900 ? `${value.slice(0, 900)}…` : value;
}
async function copyNotePath(path: string | null | undefined) {
  if (!path) return;
  const session = selectedSession.value;
  try {
    await navigator.clipboard.writeText(path);
    session?.logs.push(`已复制笔记路径：${path}`);
  } catch (err) {
    console.warn("无法直接复制到剪贴板", err);
    window.prompt("复制以下笔记路径", path);
    session?.logs.push("请手动复制笔记路径");
  }
}

const lifetime = new AbortController();
let detailController: AbortController | null = null;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let creationVersion = 0;
let disposed = false;
const storageKey = "deep-research-selected-id";
function remember(id: string | null) {
  try { if (id) sessionStorage.setItem(storageKey, id); else sessionStorage.removeItem(storageKey); } catch { /* Storage is optional. */ }
}
function detachView() {
  clearTimeout(retryTimer);
  retryTimer = undefined;
  detailController?.abort();
  detailController = null;
}
function mergeSummary(item: ResearchSummary) {
  const index = researches.value.findIndex(row => row.research_id === item.research_id);
  if (index < 0) researches.value.unshift(item);
  else if (researches.value[index].snapshot_seq <= item.snapshot_seq) researches.value[index] = item;
}
function updateSummary(session: ResearchSession) {
  const previous = researches.value.find(row => row.research_id === session.id);
  if (!previous) return;
  mergeSummary({ ...previous, topic: session.topic, status: session.status, snapshot_seq: session.lastSeq,
    report_available: Boolean(session.report), error: session.outcome?.error || null,
    progress: { total_tasks: session.tasks.length, completed_tasks: session.tasks.filter(task => task.status === "completed").length } });
}
async function refreshResearches() {
  if (refreshing.value || disposed) return;
  refreshing.value = true;
  const version = creationVersion;
  try {
    const result = await listResearches(lifetime.signal);
    if (disposed || version !== creationVersion) return;
    const previous = new Map(researches.value.map(row => [row.research_id, row]));
    researches.value = result.researches.map(row => {
      const old = previous.get(row.research_id);
      return old && old.snapshot_seq > row.snapshot_seq ? old : row;
    });
    listError.value = "";
    for (const row of result.researches) {
      const session = sessions[row.research_id];
      if (session && row.snapshot_seq >= session.lastSeq) session.status = row.status;
    }
    const selected = selectedSession.value;
    if (selected && !result.researches.some(row => row.research_id === selected.id)) {
      detachView();
      selected.connection = "missing";
      selected.connectionError = "当前后端已无此研究记录。服务重启后内存记录会清空。";
      remember(null);
    }
  } catch (err) {
    if (!disposed) listError.value = `研究列表读取失败：${err instanceof Error ? err.message : "连接异常"}`;
  } finally { refreshing.value = false; }
}

async function selectResearch(id: string) {
  const item = researches.value.find(row => row.research_id === id);
  if (!item || disposed) return;
  detachView();
  activeResearchId.value = id;
  isExpanded.value = true;
  remember(id);
  if (!sessions[id]) sessions[id] = createSession(item);
  const session = sessions[id];
  session.connection = "connecting";
  session.connectionError = "";
  const controller = new AbortController();
  detailController = controller;
  const isCurrent = () => !disposed && detailController === controller && activeResearchId.value === id;
  try {
    const snapshot = await getResearch(id, controller.signal);
    if (!isCurrent()) return;
    applySnapshot(session, snapshot);
    mergeSummary(snapshot);
    if (!isResearchActive(session.status)) { session.connection = "ended"; return; }
    session.connection = "live";
    await watchResearchEvents(id, event => {
      if (!isCurrent()) return;
      if (applyResearchEvent(session, event)) updateSummary(session);
    }, { signal: controller.signal, after: session.lastSeq });
    if (isCurrent() && session.outcome === null) throw new Error("事件连接已结束，正在重新同步后台状态");
  } catch (err) {
    if (!isCurrent() || controller.signal.aborted) return;
    const missing = err instanceof ResearchAPIError && err.status === 404;
    session.connection = missing ? "missing" : "offline";
    session.connectionError = missing ? "当前后端已无此研究记录，可能已重启。"
      : `进度连接异常：${err instanceof Error ? err.message : "请求失败"}。后台研究不会因此取消，将尝试重新同步。`;
    if (!missing) retryTimer = setTimeout(() => { if (isCurrent() && isExpanded.value) void selectResearch(id); }, 3000);
  }
}

async function handleSubmit() {
  if (submitting.value) return;
  if (!form.topic.trim()) { error.value = "请输入研究主题"; return; }
  submitting.value = true;
  error.value = "";
  try {
    const snapshot = await createResearch({ topic: form.topic.trim(), search_api: form.searchApi || undefined }, lifetime.signal);
    if (disposed) return;
    creationVersion++;
    mergeSummary(snapshot);
    sessions[snapshot.research_id] = createSession(snapshot);
    applySnapshot(sessions[snapshot.research_id], snapshot);
    void selectResearch(snapshot.research_id);
  } catch (err) {
    if (!disposed) error.value = err instanceof ResearchAPIError && err.status === 429
      ? "研究名额已满，请等待研究结束或取消等待项后再提交。"
      : `提交研究未成功确认：${err instanceof Error ? err.message : "连接异常"}。可刷新列表核对。`;
  } finally { submitting.value = false; }
}

async function cancelResearch(id: string | null) {
  if (!id || cancelling[id]) return;
  cancelling[id] = true;
  actionErrors[id] = "";
  try {
    const snapshot = await cancelResearchById(id, lifetime.signal);
    if (disposed) return;
    mergeSummary(snapshot);
    if (!sessions[id]) sessions[id] = createSession(snapshot);
    applySnapshot(sessions[id], snapshot);
    if (sessions[id].status === "CANCELLING") sessions[id].notice = "取消请求已接收，等待当前调用退出并完成清理。";
    void refreshResearches();
  } catch (err) {
    if (!disposed) actionErrors[id] = `取消未确认：${err instanceof Error ? err.message : "请求失败"}`;
  } finally { cancelling[id] = false; }
}
function goBack() { detachView(); isExpanded.value = false; }
function startNewResearch() { goBack(); form.topic = ""; form.searchApi = ""; error.value = ""; }

onMounted(async () => {
  await refreshResearches();
  if (disposed) return;
  let saved: string | null = null;
  try { saved = sessionStorage.getItem(storageKey); } catch { /* Storage is optional. */ }
  if (!activeResearchId.value && saved && researches.value.some(row => row.research_id === saved)) void selectResearch(saved);
  pollTimer = setInterval(() => { void refreshResearches(); }, 3000);
});
onBeforeUnmount(() => { disposed = true; lifetime.abort(); detachView(); clearInterval(pollTimer); });
</script>


<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
  padding: 72px 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  background: radial-gradient(circle at 20% 20%, #f8fafc, #dbeafe 60%);
  color: #1f2937;
  overflow: hidden;
  box-sizing: border-box;
  transition: padding 0.4s ease;
}

.app-shell.expanded {
  padding: 0;
  align-items: stretch;
}

.aurora {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.55;
}

.aurora span {
  position: absolute;
  width: 45vw;
  height: 45vw;
  max-width: 520px;
  max-height: 520px;
  background: radial-gradient(circle, rgba(148, 197, 255, 0.35), transparent 60%);
  filter: blur(90px);
  animation: float 26s infinite linear;
}

.aurora span:nth-child(1) {
  top: -20%;
  left: -18%;
  animation-delay: 0s;
}

.aurora span:nth-child(2) {
  bottom: -25%;
  right: -20%;
  background: radial-gradient(circle, rgba(166, 139, 255, 0.28), transparent 60%);
  animation-delay: -9s;
}

.aurora span:nth-child(3) {
  top: 35%;
  left: 45%;
  background: radial-gradient(circle, rgba(164, 219, 216, 0.26), transparent 60%);
  animation-delay: -16s;
}

.layout {
  position: relative;
  width: 100%;
  display: flex;
  gap: 24px;
  z-index: 1;
  transition: all 0.4s ease;
}

.layout-centered {
  max-width: 600px;
  justify-content: center;
  align-items: center;
}

.layout-fullscreen {
  height: 100vh;
  max-width: 100%;
  gap: 0;
  align-items: stretch;
}

.panel {
  position: relative;
  flex: 1 1 360px;
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 24px 48px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
  overflow: hidden;
}

.panel-form {
  max-width: 420px;
}

.panel-centered {
  width: 100%;
  max-width: 600px;
  padding: 40px;
  box-shadow: 0 32px 64px rgba(15, 23, 42, 0.15);
  transform: scale(1);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.panel-centered:hover {
  transform: scale(1.02);
  box-shadow: 0 40px 80px rgba(15, 23, 42, 0.2);
}

.panel-result {
  min-width: 0;
  flex: 2 1 420px;
}

.panel::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(125, 86, 255, 0.1));
  opacity: 0;
  transition: opacity 0.35s ease;
  z-index: 0;
}

.panel:hover::before {
  opacity: 1;
}

.panel-result {
  background: #f8fafc;
}

.panel-result::before {
  content: none;
}

.panel-result .tasks-list,
.panel-result .task-detail,
.panel-result .report-block,
.panel-result .sources-block,
.panel-result .summary-block,
.panel-result .tools-block {
  background: #ffffff;
}

.panel > * {
  position: relative;
  z-index: 1;
}

.panel-form h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: 0.01em;
}

.panel-form p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.logo {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  box-shadow: 0 12px 28px rgba(59, 130, 246, 0.4);
}

.logo svg {
  width: 28px;
  height: 28px;
  fill: #f8fafc;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field span {
  font-weight: 600;
  color: #475569;
}

textarea,
input,
select {
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.92);
  color: #1f2937;
  font-size: 14px;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

textarea:focus,
input:focus,
select:focus {
  outline: none;
  border-color: rgba(37, 99, 235, 0.65);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  background: #ffffff;
}

.options {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.option {
  flex: 1;
  min-width: 140px;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.submit {
  align-self: flex-start;
  padding: 12px 24px;
  border-radius: 16px;
  border: none;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  position: relative;
}

.submit-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.submit .spinner {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: rgba(255, 255, 255, 0.85);
  stroke-linecap: round;
  animation: spin 1s linear infinite;
}

.submit:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.submit:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.28);
}

.secondary-btn {
  padding: 10px 18px;
  border-radius: 14px;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.28);
  color: #1f2937;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.secondary-btn:hover {
  background: rgba(148, 163, 184, 0.2);
  border-color: rgba(148, 163, 184, 0.35);
  color: #0f172a;
}

.error-chip {
  margin-top: 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 14px;
  color: #b91c1c;
  font-size: 14px;
}

.error-chip svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.panel-result {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.status-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.status-controls {
  display: flex;
  gap: 8px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(191, 219, 254, 0.28);
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 13px;
  color: #1f2937;
  border: 1px solid rgba(59, 130, 246, 0.35);
  transition: background 0.3s ease, color 0.3s ease;
}

.status-chip.active {
  background: rgba(129, 140, 248, 0.2);
  border-color: rgba(129, 140, 248, 0.4);
  color: #1e293b;
}

.status-chip .dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 12px rgba(37, 99, 235, 0.45);
  animation: pulse 1.8s ease-in-out infinite;
}

.status-meta {
  color: #64748b;
  font-size: 13px;
}

.timeline-wrapper {
  margin-top: 12px;
  max-height: 220px;
  overflow-y: auto;
  padding-right: 8px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.45) rgba(226, 232, 240, 0.6);
}

.timeline-wrapper::-webkit-scrollbar {
  width: 6px;
}

.timeline-wrapper::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.6);
  border-radius: 999px;
}

.timeline-wrapper::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(129, 140, 248, 0.8), rgba(59, 130, 246, 0.7));
  border-radius: 999px;
}

.timeline-wrapper::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.9), rgba(37, 99, 235, 0.8));
}

.timeline {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
  padding-left: 12px;
}

.timeline::before {
  content: "";
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 0;
  width: 2px;
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.35), rgba(129, 140, 248, 0.15));
}

.timeline li {
  position: relative;
  padding-left: 24px;
  color: #1e293b;
  font-size: 14px;
  line-height: 1.5;
}

.timeline-node {
  position: absolute;
  left: -12px;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #38bdf8, #7c3aed);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.22);
}

.timeline-enter-active,
.timeline-leave-active {
  transition: all 0.35s ease, opacity 0.35s ease;
}

.timeline-enter-from,
.timeline-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.tasks-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.tasks-list {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
}

.tasks-list h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.tasks-list ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.task-item {
  flex: 1 1 190px;
  min-width: 0;
  border-radius: 14px;
  border: 1px solid transparent;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.task-item.completed {
  border-color: rgba(56, 189, 248, 0.35);
  background: rgba(191, 219, 254, 0.28);
}

.task-item.active {
  border-color: rgba(129, 140, 248, 0.5);
  background: rgba(224, 231, 255, 0.5);
}

.task-button {
  width: 100%;
  height: 100%;
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.task-title {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
  font-size: 14px;
  color: #1e293b;
}

.task-status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  color: #1f2937;
  background: rgba(148, 163, 184, 0.2);
}

.task-status.pending {
  background: rgba(148, 163, 184, 0.18);
  color: #475569;
}

.task-status.in_progress {
  background: rgba(129, 140, 248, 0.24);
  color: #312e81;
}

.task-status.completed {
  background: rgba(34, 197, 94, 0.2);
  color: #15803d;
}

.task-status.failed,
.task-status.skipped {
  background: rgba(248, 113, 113, 0.18);
  color: #b91c1c;
}

.task-intent {
  margin: 0;
  padding: 0 14px 12px 14px;
  font-size: 13px;
  color: #64748b;
}

.task-detail {
  min-width: 0;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.5);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}

.task-chip-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.task-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.task-header .muted {
  margin: 6px 0 0;
}

.task-label {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(191, 219, 254, 0.32);
  border: 1px solid rgba(59, 130, 246, 0.35);
  font-size: 12px;
  color: #1e3a8a;
}

.task-label.note-chip {
  background: rgba(34, 197, 94, 0.2);
  border-color: rgba(34, 197, 94, 0.35);
  color: #15803d;
}

.task-label.path-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 360px;
  background: rgba(56, 189, 248, 0.2);
  border-color: rgba(56, 189, 248, 0.35);
  color: #0369a1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-label {
  font-weight: 500;
}

.path-text {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-action {
  border: none;
  background: rgba(56, 189, 248, 0.2);
  color: #0369a1;
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.chip-action:hover {
  background: rgba(14, 165, 233, 0.28);
  color: #0f172a;
}

.task-notices {
  background: rgba(191, 219, 254, 0.28);
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 16px;
  padding: 14px 18px;
  color: #1f2937;
}

.task-notices h4 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.task-notices ul {
  list-style: disc;
  margin: 0 0 0 18px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-notices li {
  font-size: 13px;
}

.report-block {
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 18px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.report-block h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.block-pre {
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1f2937;
  background: rgba(248, 250, 252, 0.9);
  padding: 16px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  overflow: auto;
  max-height: 420px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.6) rgba(226, 232, 240, 0.7);
}

.block-pre::-webkit-scrollbar {
  width: 6px;
}

.block-pre::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.7);
  border-radius: 999px;
}

.block-pre::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.75), rgba(59, 130, 246, 0.65));
  border-radius: 999px;
}

.block-pre::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, rgba(79, 70, 229, 0.8), rgba(37, 99, 235, 0.75));
}

.summary-block .block-pre,
.sources-block .block-pre {
  max-height: 360px;
}


.tools-block {
  position: relative;
  margin-top: 16px;
  padding: 20px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tools-block h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: 0.02em;
}

.tool-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-entry {
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-entry-header {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.tool-entry-title {
  font-weight: 600;
  color: #1f2937;
}

.tool-entry-note {
  font-size: 12px;
  color: #0f766e;
}

.tool-entry-path {
  margin: 0;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #2563eb;
}

.tool-subtitle {
  margin: 0;
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}

.tool-pre {
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1f2937;
  background: rgba(248, 250, 252, 0.9);
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  overflow: auto;
  max-height: 260px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.6) rgba(226, 232, 240, 0.7);
}

.tool-pre::-webkit-scrollbar {
  width: 6px;
}

.tool-pre::-webkit-scrollbar-track {
  background: rgba(226, 232, 240, 0.7);
}

.tool-pre::-webkit-scrollbar-thumb {
  background: rgba(99, 102, 241, 0.7);
  border-radius: 10px;
}

.link-btn {
  background: none;
  border: none;
  color: #0369a1;
  cursor: pointer;
  padding: 0 4px;
  font-size: 12px;
  border-radius: 8px;
  transition: color 0.2s ease, background 0.2s ease;
}

.link-btn:hover {
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.16);
}


.sources-block,
.summary-block {
  position: relative;
  margin-top: 16px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.4);
}

.sources-history {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sources-history h4 {
  margin: 0;
  color: #1f2937;
  font-size: 14px;
  letter-spacing: 0.01em;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-list details {
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 14px;
  padding: 12px 16px;
  color: #1f2937;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.history-list details[open] {
  background: rgba(224, 231, 255, 0.55);
  border-color: rgba(129, 140, 248, 0.4);
}

.history-list summary {
  cursor: pointer;
  font-weight: 600;
  outline: none;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history-list summary::-webkit-details-marker {
  display: none;
}

.history-list summary::after {
  content: "▾";
  margin-left: 6px;
  font-size: 12px;
  opacity: 0.7;
  transition: transform 0.2s ease;
}

.history-list details[open] summary::after {
  transform: rotate(180deg);
}

.block-highlight {
  animation: glow 1.2s ease;
}

.sources-block h3,
.summary-block h3 {
  margin: 0 0 14px;
  color: #1f2937;
  letter-spacing: 0.02em;
}

.sources-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-item {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  gap: 6px;
}

.source-link {
  color: #2563eb;
  text-decoration: none;
  font-weight: 600;
  letter-spacing: 0.01em;
  transition: color 0.2s ease;
}

.source-link::after {
  content: " ↗";
  font-size: 12px;
  opacity: 0.6;
}

.source-link:hover {
  color: #0f172a;
}

.source-tooltip {
  display: none;
  position: absolute;
  bottom: calc(100% + 12px);
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.98);
  color: #1f2937;
  padding: 14px 16px;
  border-radius: 16px;
  box-shadow: 0 18px 32px rgba(15, 23, 42, 0.18);
  width: min(420px, 90vw);
  z-index: 20;
  border: 1px solid rgba(148, 163, 184, 0.24);
}

.source-tooltip::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border-width: 10px;
  border-style: solid;
  border-color: rgba(255, 255, 255, 0.98) transparent transparent transparent;
}

.source-tooltip::before {
  content: "";
  position: absolute;
  bottom: -12px;
  left: 50%;
  transform: translateX(-50%);
  border-width: 12px 10px 0 10px;
  border-style: solid;
  border-color: rgba(255, 255, 255, 0.98) transparent transparent transparent;
  filter: drop-shadow(0 -2px 4px rgba(15, 23, 42, 0.12));
}

.source-tooltip p {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.6;
}

.source-tooltip p:last-child {
  margin-bottom: 0;
}

.muted-text {
  color: #64748b;
}

.source-item:hover .source-tooltip,
.source-item:focus-within .source-tooltip {
  display: block;
}

.hint.muted {
  color: #64748b;
}

@keyframes float {
  0% {
    transform: translate3d(0, 0, 0) rotate(0deg);
  }
  50% {
    transform: translate3d(10%, 6%, 0) rotate(3deg);
  }
  100% {
    transform: translate3d(0, 0, 0) rotate(0deg);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.3);
    opacity: 0.5;
  }
}

@keyframes glow {
  0% {
    box-shadow: 0 0 0 rgba(59, 130, 246, 0.3);
    border-color: rgba(59, 130, 246, 0.5);
  }
  100% {
    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.12);
    border-color: rgba(148, 163, 184, 0.2);
  }
}

@media (max-width: 960px) {
  .app-shell {
    padding: 56px 16px;
  }

  .layout-centered {
    flex-direction: column;
    align-items: stretch;
  }

  .panel {
    padding: 22px;
  }

  .panel-form,
  .panel-result {
    max-width: none;
  }

  .status-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .status-main,
  .status-controls {
    width: 100%;
  }

  .status-controls {
    justify-content: flex-start;
  }
}

@media (max-width: 600px) {
  .options {
    flex-direction: column;
  }

  .status-meta {
    font-size: 12px;
  }

  .panel-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .panel-form h1 {
    font-size: 24px;
  }
}

/* 侧边栏样式 */
.sidebar {
  width: 400px;
  min-width: 400px;
  height: 100vh;
  background: rgba(255, 255, 255, 0.98);
  border-right: 1px solid rgba(148, 163, 184, 0.2);
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto;
  box-shadow: 4px 0 24px rgba(15, 23, 42, 0.08);
}

.sidebar-header {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-header h2 {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  color: #1f2937;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: transparent;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 12px;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  width: fit-content;
}

.back-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.1);
  border-color: #3b82f6;
  color: #3b82f6;
}

.back-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.research-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-item label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}

.info-item p {
  margin: 0;
  font-size: 14px;
  color: #1f2937;
  line-height: 1.6;
}

.topic-display {
  font-size: 16px !important;
  font-weight: 600;
  color: #0f172a !important;
  padding: 12px;
  background: rgba(59, 130, 246, 0.05);
  border-radius: 8px;
  border-left: 3px solid #3b82f6;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 13px !important;
  color: #64748b !important;
  font-weight: 500;
}

.sidebar-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.2);
}

.new-research-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  border: none;
  border-radius: 12px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.new-research-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4);
}

.new-research-btn:active {
  transform: translateY(0);
}

/* 全屏状态下的结果面板 */
.layout-fullscreen .panel-result {
  flex: 1;
  height: 100vh;
  border-radius: 0;
  border: none;
  overflow-y: auto;
  max-width: none;
}

@media (max-width: 1024px) {
  .sidebar {
    width: 320px;
    min-width: 320px;
  }
}

@media (max-width: 768px) {
  .layout-fullscreen {
    flex-direction: column;
    height: auto;
    min-height: 100vh;
  }

  .sidebar {
    width: 100%;
    min-width: 100%;
    height: auto;
    max-height: none;
  }

  .layout-fullscreen .panel-result {
    height: auto;
    min-height: 60vh;
    overflow-y: visible;
  }
}

/* Research overview hierarchy and presentation-only view switches. */
.research-overview {
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 14px;
}

.research-overview-heading {
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  list-style: none;
  cursor: pointer;
}

.research-overview-heading::-webkit-details-marker {
  display: none;
}

.overview-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.overview-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.disclosure-action {
  color: #2563eb;
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
}

.disclosure-collapse,
.research-overview[open] .disclosure-expand {
  display: none;
}

.research-overview[open] .disclosure-collapse {
  display: inline;
}

.research-overview .topic-display {
  width: 100%;
  overflow-wrap: anywhere;
}

.research-overview-body {
  margin: 0 16px 16px;
  padding: 16px 0 0 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.2);
  border-left: 2px solid rgba(148, 163, 184, 0.2);
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.research-overview-body .status-meta {
  margin: 0;
}

.flow-toggle {
  width: 100%;
  padding: 8px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: transparent;
  border: none;
  color: #1f2937;
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.research-flow .timeline-wrapper {
  max-height: none;
  overflow: visible;
  padding: 0;
}

.research-flow .timeline p {
  margin: 0;
  overflow-wrap: anywhere;
}

.result-tabs,
.task-detail-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.22);
}

.view-tab {
  padding: 10px 16px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.94);
  color: #475569;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}

.view-tab[aria-pressed="true"] {
  background: rgba(191, 219, 254, 0.36);
  border-color: rgba(59, 130, 246, 0.6);
  color: #1d4ed8;
}

.view-tab:hover {
  border-color: #3b82f6;
}

.view-tab:focus-visible,
.task-button:focus-visible,
.flow-toggle:focus-visible,
.research-overview-heading:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 3px;
}

.task-detail .sources-block,
.task-detail .summary-block,
.task-detail .tools-block {
  margin-top: 0;
}

.task-detail .block-pre,
.report-block .block-pre,
.tool-pre {
  max-height: none;
  overflow: visible;
}

.task-chip-group,
.task-label,
.tool-entry-title,
.task-header h3 {
  min-width: 0;
  overflow-wrap: anywhere;
}

.view-empty {
  margin: 0;
  padding: 22px;
}

.status-chip.partial {
  color: #92400e;
  background: #fffbeb;
  border-color: #fcd34d;
}

.status-chip.failed {
  color: #991b1b;
  background: #fef2f2;
  border-color: #fca5a5;
}

.status-chip:not(.active) .dot {
  animation: none;
  box-shadow: none;
}

.research-result-notice {
  margin: 0;
  padding: 12px 16px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 12px;
  overflow-wrap: anywhere;
}

.research-result-notice.failed {
  color: #991b1b;
  background: #fef2f2;
  border-color: #fca5a5;
}
/* M1 keeps the detail layout and gives the list its own compact scroll area. */
.form-research-list { margin-top: 28px; border-top: 1px solid #e2e8f0; padding-top: 22px; }
.panel-centered:hover { transform: none; }
.sidebar > .research-list, .sidebar-header, .sidebar-actions { flex-shrink: 0; }
.research-info { flex-shrink: 0; }
</style>
