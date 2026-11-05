<template>
  <section class="research-list" aria-label="研究列表">
    <header>
      <div><h3>研究列表</h3><p>{{ activeCount }} 项运行 · {{ queuedCount }} 项等待</p></div>
      <button type="button" class="refresh" :disabled="refreshing" @click="$emit('refresh')">{{ refreshing ? '刷新中' : '刷新' }}</button>
    </header>
    <p v-if="error" class="list-error" role="status">{{ error }}</p>
    <p v-if="!items.length" class="empty">{{ refreshing ? '正在读取研究列表…' : '暂无研究记录。' }}</p>
    <ul v-else>
      <li v-for="item in items" :key="item.research_id" :class="{ selected: item.research_id === selectedId }">
        <button type="button" class="research-select" :aria-pressed="item.research_id === selectedId" @click="$emit('select', item.research_id)">
          <span class="title">{{ item.topic }}</span>
          <span class="row"><span class="status" :class="item.status.toLowerCase()">{{ STATUS_LABEL[item.status] || item.status }}</span><span>{{ item.progress.completed_tasks }}/{{ item.progress.total_tasks }} 任务完成</span></span>
          <span class="row"><span>{{ item.report_available ? '报告已生成' : '尚无报告' }}</span><time :datetime="item.created_at">{{ formatTime(item.created_at) }}</time></span>
          <span class="research-id" :title="item.research_id">ID：{{ item.research_id.slice(0, 12) }}{{ item.history_only ? " · 历史" : "" }}</span>
        </button>
        <button v-if="isResearchActive(item.status)" type="button" class="cancel"
          :aria-label="`取消研究：${item.topic}`" :disabled="cancelling[item.research_id] || item.status === 'CANCELLING'"
          @click="$emit('cancel', item.research_id)">{{ cancelling[item.research_id] || item.status === 'CANCELLING' ? '取消中…' : '取消研究' }}</button>
        <p v-if="actionErrors[item.research_id]" class="list-error" role="status">{{ actionErrors[item.research_id] }}</p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ResearchSummary } from "../services/api";
import { isResearchActive, STATUS_LABEL } from "../services/researchState";
const props = defineProps<{
  items: ResearchSummary[]; selectedId: string | null; refreshing: boolean; error: string;
  cancelling: Record<string, boolean>; actionErrors: Record<string, string>;
}>();
defineEmits<{ select: [id: string]; cancel: [id: string]; refresh: [] }>();
const activeCount = computed(() => props.items.filter(item => ["RUNNING", "CANCELLING"].includes(item.status)).length);
const queuedCount = computed(() => props.items.filter(item => item.status === "PENDING").length);
function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
  });
}
</script>

<style scoped>
.research-list { min-width: 0; }
header, .row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
header { margin-bottom: 12px; }
h3 { margin: 0; color: #1f2937; font-size: 16px; }
header p, .empty { margin: 6px 0 0; color: #64748b; font-size: 12px; }
button { font: inherit; cursor: pointer; }
button:disabled { cursor: default; opacity: .6; }
.refresh, .cancel { border: 1px solid #dbe3ed; border-radius: 8px; padding: 6px 10px; background: white; color: #475569; font-size: 12px; }
ul { list-style: none; padding: 0 4px 0 0; margin: 0; max-height: 340px; overflow-y: auto; display: grid; gap: 10px; }
li { border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; background: #fff; }
li.selected { border-color: #93b4ff; background: #f1f6ff; }
.research-select { width: 100%; border: 0; padding: 12px; display: grid; gap: 9px; background: transparent; text-align: left; }
.title { color: #1e293b; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.row { color: #64748b; font-size: 11px; flex-wrap: wrap; }
.status { color: #475569; border-radius: 20px; padding: 3px 7px; background: #f1f5f9; }
.status.running { color: #1d4ed8; background: #dbeafe; }
.status.completed { color: #15803d; background: #dcfce7; }
.status.failed { color: #b91c1c; background: #fee2e2; }
.status.partial, .status.cancelling, .status.interrupted { color: #92400e; background: #fef3c7; }
.research-id { color: #94a3b8; font-size: 10px; }
.cancel { margin: 0 12px 10px; }
.list-error { margin: 8px 12px; font-size: 12px; color: #b91c1c; overflow-wrap: anywhere; }
button:focus-visible { outline: 2px solid #2563eb; outline-offset: -2px; }
</style>
