// How a tool call the model made reads in a reply: one line while it runs and when it is done, with details to open.
import { bodyOf, textEl } from "./core.js";

// ---- tool calls ----
// A tool the model called shows as a line above the answer: "Searching the web for ..." while it runs, then
// "Searched the web for ..." that opens to the results. How each tool reads is in TOOL_UI; others get a plain line.
const hostOf = (url) => new URL(url).hostname.replace(/^www\./, "");
const isWebUrl = (url) => { try { return ["http:", "https:"].includes(new URL(url).protocol); } catch { return false; } };

const safeHost = (url) => { try { return hostOf(url); } catch { return ""; } };
const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

const TOOL_UI = {
  calculator: {
    running: (args) => `Calculating ${args.expression ?? ""}…`,
    done: (args, shown) => `${shown.expression} = ${shown.result}`,
    failed: (error) => `Calculator: ${error}`,
    stopped: "Calculation stopped",
  },
  search_chats: {
    running: (args) => `Searching your chats for “${args.query ?? ""}”…`,
    done: (args, shown) => `Searched your chats for “${shown.query}” · ${shown.results.length ? plural(shown.results.length, "chat") : "no matches"}`,
    failed: (error) => `Chat search failed: ${error}`,
    stopped: "Chat search stopped",
    detail: (shown) => {
      const list = document.createElement("ol");
      for (const r of shown.results) {
        const item = document.createElement("li");
        const link = Object.assign(textEl("a", r.title), { href: `#${encodeURIComponent(r.id)}` }); // a chat in this app
        item.append(link, textEl("p", r.snippet));
        list.append(item);
      }
      return list;
    },
  },
  fetch_url: {
    running: (args) => `Reading ${safeHost(args.url) || "the page"}…`,
    done: (args, shown) => `Read ${shown.title || safeHost(shown.url) || "a page"}`,
    failed: (error) => `Couldn't read the page: ${error}`,
    stopped: "Reading the page stopped",
    detail: (shown) => {
      const box = document.createElement("div");
      if (isWebUrl(shown.url)) { // the URL came from the model: web links only
        box.append(Object.assign(textEl("a", shown.url), { href: shown.url, target: "_blank", rel: "noopener noreferrer" }));
      }
      // saved from before pages came in parts have no offset or total
      const from = shown.offset ? ` from character ${shown.offset.toLocaleString()}` : "";
      const total = shown.total ? ` of ${shown.total.toLocaleString()}` : "";
      const more = shown.truncated ? "; there is more" : "";
      box.append(textEl("p", `${plural(shown.characters, "character")} read${from}${total}${more}`));
      return box;
    },
  },
  web_search: {
    running: (args) => `Searching the web for “${args.query ?? ""}”…`,
    done: (args, shown) => {
      const n = shown.results.length;
      return `Searched the web for “${shown.query}” · ${n ? `${n} result${n === 1 ? "" : "s"}` : "no results"}`;
    },
    failed: (error) => `Web search failed: ${error}`,
    stopped: "Web search stopped",
    detail: (shown) => {
      const list = document.createElement("ol");
      for (const r of shown.results.filter((r) => isWebUrl(r.url))) { // URLs from the web are untrusted: web links only
        const item = document.createElement("li");
        const link = Object.assign(document.createElement("a"), { href: r.url, target: "_blank", rel: "noopener noreferrer", textContent: r.title });
        item.append(link, Object.assign(document.createElement("span"), { className: "domain", textContent: hostOf(r.url) }));
        if (r.description) item.append(Object.assign(document.createElement("p"), { textContent: r.description }));
        list.append(item);
      }
      return list;
    },
  },
};

export function renderToolCall(el, call) {
  let box = el.querySelector(".tool-calls");
  if (!box) {
    box = Object.assign(document.createElement("div"), { className: "tool-calls" });
    bodyOf(el).before(box);
  }
  let row = [...box.children].find((d) => d.dataset.id === call.id);
  if (!row) {
    row = document.createElement("details");
    row.className = "tool-call";
    row.dataset.id = call.id;
    row.dataset.name = call.name;
    row.innerHTML = '<summary></summary><div class="tool-body"></div>';
    box.append(row);
  }
  const ui = TOOL_UI[call.name];
  row.querySelector("summary").dir = "auto";
  row.dataset.status = call.status;
  row.setAttribute("aria-busy", String(call.status === "running"));
  let summary, detail = null;
  try {
    summary = {
      running: () => ui?.running(call.arguments ?? {}) ?? `Using ${call.name}…`,
      done: () => ui?.done(call.arguments ?? {}, call.display) ?? `Used ${call.name}`,
      error: () => ui?.failed(call.error) ?? `${call.name} failed: ${call.error}`,
      stopped: () => ui?.stopped ?? `${call.name} stopped`,
    }[call.status]();
    detail = call.status === "done" ? ui?.detail?.(call.display) : null;
  } catch {
    // Saved details this page doesn't expect (from an older version, or an imported file) must not break the
    // whole conversation: it falls back to a plain line.
    summary = `Used ${call.name}`;
  }
  row.querySelector("summary").textContent = summary;
  row.querySelector(".tool-body").replaceChildren(...(detail ? [detail] : []));
}
