<template>
  <div class="markdown-content" v-html="renderedContent"></div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../services/markdown";
import "katex/dist/katex.min.css";

const props = defineProps<{ content: string }>();
const renderedContent = computed(() => renderMarkdown(props.content));
</script>

<style scoped>
.markdown-content {
  min-width: 0;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.markdown-content :deep(> :first-child) {
  margin-top: 0;
}

.markdown-content :deep(> :last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  margin: 1.4em 0 0.6em;
  color: #0f172a;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-content :deep(h1) { font-size: 1.7em; }
.markdown-content :deep(h2) { font-size: 1.45em; }
.markdown-content :deep(h3) { font-size: 1.2em; }
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) { font-size: 1em; }

.markdown-content :deep(p) {
  margin: 0.8em 0;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.8em 0;
  padding-left: 1.8em;
}

.markdown-content :deep(li + li) {
  margin-top: 0.35em;
}

.markdown-content :deep(blockquote) {
  margin: 1em 0;
  padding: 0.5em 1em;
  border-left: 3px solid #93b4f6;
  background: #f1f5fb;
  color: #475569;
}

.markdown-content :deep(a) {
  color: #2563eb;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.markdown-content :deep(code) {
  padding: 0.15em 0.35em;
  border-radius: 4px;
  background: #f1f5f9;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.9em;
}

.markdown-content :deep(pre) {
  max-width: 100%;
  margin: 1em 0;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  overflow-x: auto;
  white-space: pre;
  overflow-wrap: normal;
  font-size: 13px;
  line-height: 1.65;
}

.markdown-content :deep(pre code) {
  padding: 0;
  background: transparent;
  font-size: inherit;
}

.markdown-content :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  margin: 1em 0;
  border-collapse: collapse;
  overflow-x: auto;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  min-width: 100px;
  padding: 9px 12px;
  border: 1px solid #dce4ef;
  vertical-align: top;
}

.markdown-content :deep(th) {
  background: #f1f5fb;
  font-weight: 600;
}

.markdown-content :deep(hr) {
  margin: 1.5em 0;
  border: 0;
  border-top: 1px solid #e2e8f0;
}

.markdown-content :deep(img) {
  max-width: 100%;
  height: auto;
}

.markdown-content :deep(.katex-display) {
  max-width: 100%;
  margin: 1em 0;
  padding: 0.3em 0;
  overflow-x: auto;
  overflow-y: hidden;
}
</style>
