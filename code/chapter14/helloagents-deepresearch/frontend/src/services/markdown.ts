import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import { katex } from "@mdit/plugin-katex";

const markdown = new MarkdownIt({
  html: false,
  linkify: true
}).use(katex, {
  delimiters: "all",
  throwOnError: false,
  trust: false
});

const defaultLinkRenderer = markdown.renderer.rules.link_open;
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index];
  const href = String(token.attrGet("href") || "");
  if (/^https?:\/\//i.test(href)) {
    token.attrSet("target", "_blank");
    token.attrSet("rel", "noopener noreferrer");
  }
  return defaultLinkRenderer
    ? defaultLinkRenderer(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options);
};

export function renderMarkdown(content: string): string {
  try {
    // Sanitize after Markdown and math rendering; preserve KaTeX MathML/SVG.
    return DOMPurify.sanitize(markdown.render(content), {
      ADD_ATTR: ["target"]
    });
  } catch (error) {
    console.warn("Markdown 渲染失败，显示原始文本", error);
    return `<pre>${markdown.utils.escapeHtml(content)}</pre>`;
  }
}
