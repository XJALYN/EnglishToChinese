const API = window.electronAPI?.apiBase || "http://127.0.0.1:8765";
let summaryText = "";
let mindmapText = "";

const MODELS = ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"];

function fillSelect(id) {
  const el = document.getElementById(id);
  MODELS.forEach((m) => {
    const o = document.createElement("option");
    o.value = m;
    o.textContent = m;
    el.appendChild(o);
  });
}

["translate-model", "summary-model", "mindmap-model"].forEach(fillSelect);

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

async function loadSettings() {
  const res = await fetch(`${API}/api/settings`);
  const data = await res.json();
  document.getElementById("translate-model").value = data.translate_model;
  document.getElementById("summary-model").value = data.summary_model;
  document.getElementById("mindmap-model").value = data.mindmap_model;
  document.getElementById("whisper-model").value = data.whisper_model;
  document.getElementById("tts-voice").value = data.tts_voice;
  document.getElementById("hf-endpoint").value = data.hf_endpoint;
}

document.getElementById("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    dashscope_api_key: document.getElementById("api-key").value,
    translate_model: document.getElementById("translate-model").value,
    summary_model: document.getElementById("summary-model").value,
    mindmap_model: document.getElementById("mindmap-model").value,
    whisper_model: document.getElementById("whisper-model").value,
    tts_voice: document.getElementById("tts-voice").value,
    hf_endpoint: document.getElementById("hf-endpoint").value,
  };
  await fetch(`${API}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  document.getElementById("settings-status").textContent = "配置已保存";
});

document.getElementById("btn-summary").addEventListener("click", async () => {
  const out = document.getElementById("summary-output");
  out.textContent = "生成中…";
  const res = await fetch(`${API}/api/summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page_url: "" }),
  });
  const data = await res.json();
  if (!res.ok) { out.textContent = data.detail || "失败"; return; }
  summaryText = data.summary;
  out.textContent = summaryText;
});

document.getElementById("btn-mindmap").addEventListener("click", async () => {
  const out = document.getElementById("mindmap-output");
  out.textContent = "生成中…";
  const res = await fetch(`${API}/api/mindmap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summary: summaryText }),
  });
  const data = await res.json();
  if (!res.ok) { out.textContent = data.detail || "失败"; return; }
  mindmapText = data.mermaid;
  out.textContent = mindmapText;
  out.removeAttribute("data-processed");
  mermaid.run({ nodes: [out] });
});

function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
}

document.getElementById("export-summary-md").addEventListener("click", () => {
  if (!summaryText) return alert("请先生成总结");
  download("summary.md", summaryText, "text/markdown");
});
document.getElementById("export-summary-html").addEventListener("click", () => {
  if (!summaryText) return alert("请先生成总结");
  const html = `<html><head><meta charset="utf-8"><title>总结</title></head><body><pre>${summaryText}</pre></body></html>`;
  download("summary.html", html, "text/html");
});
document.getElementById("export-mindmap-md").addEventListener("click", () => {
  if (!mindmapText) return alert("请先生成思维导图");
  download("mindmap.md", "```mermaid\n" + mindmapText + "\n```", "text/markdown");
});
document.getElementById("export-mindmap-html").addEventListener("click", () => {
  if (!mindmapText) return alert("请先生成思维导图");
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"><\/script></head><body><pre class="mermaid">${mindmapText}</pre><script>mermaid.initialize({startOnLoad:true,theme:'dark'})<\/script></body></html>`;
  download("mindmap.html", html, "text/html");
});

loadSettings();
mermaid.initialize({ startOnLoad: false, theme: "dark" });
