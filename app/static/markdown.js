// Markdown -> sanitized HTML. marked, DOMPurify and highlight.js are loaded as globals (vendor/).
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

marked.use({
  renderer: {
    code({ text, lang }) {
      const name = (lang || "").split(/\s/)[0];
      const known = name && hljs.getLanguage(name);
      const html = known ? hljs.highlight(text, { language: name }).value : escapeHtml(text);
      return `<div class="code"><div class="code-bar"><span>${escapeHtml(name || "text")}</span>` +
        `<button type="button" class="code-copy">Copy</button></div>` +
        `<pre><code class="hljs">${html}</code></pre></div>`;
    },
  },
});

// Links in model output open in a new tab and never get window.opener.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

// No <img>: a remote image URL in model output would make the page send requests (and whatever the
// URL encodes) to a third party. Revisit when image output is a feature.
export const renderMarkdown = (text) => DOMPurify.sanitize(marked.parse(text), { FORBID_TAGS: ["img"] });
