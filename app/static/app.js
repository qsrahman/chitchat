const messagesEl = document.getElementById("messages");
const form = document.getElementById("form");
const input = document.getElementById("input");
const history = []; // [{role, content}]; phase 2 moves this to the server

function addMessage(role, text = "") {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  messagesEl.append(el);
  setText(el, role, text);
  return el;
}

function setText(el, role, text) {
  if (role === "assistant") el.innerHTML = DOMPurify.sanitize(marked.parse(text));
  else el.textContent = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// POST + ReadableStream: yields parsed `data: {json}` SSE events.
async function* readSSE(response) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (frame.startsWith("data: ")) yield JSON.parse(frame.slice(6));
    }
  }
}

async function send(text) {
  history.push({ role: "user", content: text });
  addMessage("user", text);
  const el = addMessage("assistant");
  let reply = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    for await (const ev of readSSE(res)) {
      if (ev.type === "delta") { reply += ev.text; setText(el, "assistant", reply); }
      else if (ev.type === "error") throw new Error(ev.message);
    }
    history.push({ role: "assistant", content: reply });
  } catch (err) {
    history.pop(); // drop the unanswered user turn so a retry stays consistent
    el.className = "msg error";
    el.textContent = `Error: ${err.message}`;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  form.querySelector("button").disabled = true;
  await send(text);
  form.querySelector("button").disabled = false;
  input.focus();
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
});
