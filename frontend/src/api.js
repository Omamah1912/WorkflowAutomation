// Thin client for the GhostStop API. Every number on screen comes through here.
export const API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const get = (path) => fetch(API + path).then(handle);

export const post = (path, body) =>
  fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(handle);

export function uploadPdfs(files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return fetch(API + "/batch", { method: "POST", body: form }).then(handle);
}

export const pageUrl = (docId, n) => `${API}/doc/${encodeURIComponent(docId)}/page/${n}.png`;
export const streamUrl = (batchId) => `${API}/stream/${batchId}`;

/** Start a batch and resolve once it has finished (used by the "replay" buttons). */
export async function runAndWait(source, onStarted) {
  const { batch_id } = await post("/batch", { source });
  onStarted?.(batch_id);
  for (;;) {
    const b = await get(`/batch/${batch_id}`);
    if (b.status !== "running") return b;
    await new Promise((r) => setTimeout(r, 700));
  }
}
