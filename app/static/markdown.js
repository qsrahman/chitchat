// Markdown -> sanitized HTML. marked, DOMPurify, highlight.js and KaTeX are loaded as globals (vendor/).
// highlight.js's "plaintext" language is its HTML escaper: no highlighting, entity-escaped output.
const escapeHtml = (text) => hljs.highlight(text, { language: "plaintext" }).value;

// Math as models write it: \( inline \), $inline$, \[ block \] and $$ either $$. marked would otherwise read
// "\(" as an escaped paren and drop the backslash, and marked-katex-extension has no \( \), so this is ours.
// Single $ follows Pandoc's rule so prices stay text: the opening $ needs a non-space after it, and the
// closing $ a non-space before it and no digit after it. "costs $5 and $10" and "$20,000 and $30,000" are
// not math; "$x$" and "$1 / \ln(x)$" are. \$ is a literal dollar sign (marked's own escape).
// An unfinished formula stays literal until its closing delimiter streams in. Code spans and fences are
// consumed by marked before these rules see them.
const renderMath = (tex, displayMode) => katex.renderToString(tex, {
  displayMode, throwOnError: false, strict: "ignore", maxSize: 20, // trust stays false: no \href / \url
});

const math = {
  extensions: [
    {
      name: "blockMath",
      level: "block",
      start: (src) => src.match(/^(?:\\\[|\$\$)/m)?.index,
      tokenizer(src) {
        const m = /^(?:\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$)[ \t]*(?:\n|$)/.exec(src);
        if (m) return { type: "blockMath", raw: m[0], tex: (m[1] ?? m[2]).trim() };
      },
      renderer: (token) => `<div class="math-block">${renderMath(token.tex, true)}</div>`,
    },
    {
      name: "inlineMath",
      level: "inline",
      start: (src) => src.match(/\\\(|(?<!\\)\$/)?.index, // an escaped \$ does not start math
      tokenizer(src) {
        const m = /^(?:\\\(([\s\S]+?)\\\)|\$\$([\s\S]+?)\$\$|\$(?!\s)((?:\\.|[^$\\])+?)(?<!\s)\$(?!\d))/.exec(src);
        if (m) return { type: "inlineMath", raw: m[0], tex: (m[1] ?? m[2] ?? m[3]).trim(), display: m[2] !== undefined };
      },
      renderer: (token) => renderMath(token.tex, token.display),
    },
  ],
};

// Answers: code blocks get a header (language, Copy) and highlighting.
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
}, math);

// Reasoning: some models (gpt-oss) stream their raw thinking as the "summary", where "17*23 ... 17*20" is
// arithmetic, not emphasis. Refuse single-delimiter emphasis (*x*, _x_) and keep **bold**, lists and code.
const baseTokenizer = new marked.Tokenizer();
const reasoningMarked = new marked.Marked(math, {
  tokenizer: {
    emStrong(...args) {
      const token = baseTokenizer.emStrong.apply(this, args);
      return token?.type === "em" ? undefined : token;
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
// KaTeX's accessible MathML wraps the formula in <semantics> with the TeX in an <annotation>; DOMPurify
// drops both by default, which would leave that TeX source as stray text.
const sanitize = (html) => DOMPurify.sanitize(html, {
  FORBID_TAGS: ["img"], ADD_TAGS: ["semantics", "annotation"], ADD_ATTR: ["encoding"],
});

export const renderMarkdown = (text) => sanitize(marked.parse(text));
export const renderReasoning = (text) => sanitize(reasoningMarked.parse(text));
