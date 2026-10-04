// Static frontend: loads data/*.json, filters in the browser, and keeps
// likes / saved / read state in localStorage (per browser, nothing leaves it).

const state = {
  items: [],
  projects: null,
  topic: "",
  prefs: loadPrefs(),
};

// ---------- persistence ----------
function loadPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem("reading-prefs") || "{}");
    return { liked: raw.liked || {}, saved: raw.saved || {}, read: raw.read || {}, hideRead: !!raw.hideRead };
  } catch {
    return { liked: {}, saved: {}, read: {}, hideRead: false };
  }
}
function savePrefs() {
  try { localStorage.setItem("reading-prefs", JSON.stringify(state.prefs)); } catch { /* storage unavailable */ }
}

// ---------- data ----------
async function fetchJSON(name) {
  // Deployed: data/ sits next to index.html. Local dev from repo root: ../data/.
  for (const base of ["data/", "../data/"]) {
    try {
      const res = await fetch(base + name, { cache: "no-cache" });
      if (res.ok) return await res.json();
    } catch { /* try next */ }
  }
  return null;
}

// Boost items whose topics you've liked before.
function likedTopicWeights() {
  const counts = {};
  for (const item of Object.values(state.prefs.liked)) {
    for (const t of item.topics || []) counts[t] = (counts[t] || 0) + 1;
  }
  return counts;
}
function personalScore(item, weights) {
  const boost = (item.topics || []).reduce((s, t) => s + Math.min(weights[t] || 0, 5), 0);
  return (item.rank || 0) * (1 + 0.1 * boost);
}

// ---------- rendering ----------
const $ = (sel) => document.querySelector(sel);
const fmtDate = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function articleNode(item) {
  const node = $("#article-tpl").content.firstElementChild.cloneNode(true);
  node.querySelector(".source").textContent = item.source;
  const time = node.querySelector("time");
  time.dateTime = item.published;
  time.textContent = fmtDate(item.published);
  node.querySelector(".kind").textContent = item.kind && item.kind !== "other" ? item.kind : "";
  node.querySelector(".level").textContent = item.enriched_by === "claude" ? item.level : "";
  const title = node.querySelector(".title");
  title.href = item.url;
  title.textContent = item.title;
  node.querySelector(".summary").textContent = item.summary || "";
  const tags = node.querySelector(".tags");
  for (const t of item.topics || []) {
    if (t === "other") continue;
    const span = document.createElement("span");
    span.textContent = t;
    tags.append(span);
  }
  const discuss = node.querySelector(".discuss");
  if (item.discussion && item.discussion !== item.url) discuss.href = item.discussion;
  else discuss.remove();

  const p = state.prefs;
  const toggles = [["like", p.liked], ["save", p.saved], ["read", p.read]];
  for (const [cls, bucket] of toggles) {
    const btn = node.querySelector("." + cls);
    btn.setAttribute("aria-pressed", String(!!bucket[item.id]));
    btn.addEventListener("click", () => {
      if (bucket[item.id]) delete bucket[item.id];
      else bucket[item.id] = cls === "read" ? true : item;
      savePrefs();
      render();
    });
  }
  // Opening an article marks it read.
  title.addEventListener("click", () => { p.read[item.id] = true; savePrefs(); setTimeout(render, 300); });
  if (p.read[item.id]) node.classList.add("is-read");
  return node;
}

function renderFeed() {
  const q = $("#search").value.trim().toLowerCase();
  const kind = $("#kind").value;
  const level = $("#level").value;
  const weights = likedTopicWeights();
  const items = state.items
    .filter((i) => !state.topic || (i.topics || []).includes(state.topic))
    .filter((i) => !kind || i.kind === kind)
    .filter((i) => !level || i.level === level)
    .filter((i) => !state.prefs.hideRead || !state.prefs.read[i.id])
    .filter((i) => !q || `${i.title} ${i.summary || ""} ${i.source}`.toLowerCase().includes(q))
    .sort((a, b) => personalScore(b, weights) - personalScore(a, weights));

  const list = $("#feed-list");
  list.replaceChildren(...items.map(articleNode));
  if (!items.length) list.innerHTML = '<li class="empty">Nothing matches these filters.</li>';
}

function renderTopics() {
  const counts = {};
  for (const i of state.items) for (const t of i.topics || []) if (t !== "other") counts[t] = (counts[t] || 0) + 1;
  const chips = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = `${t} ${n}`;
    b.setAttribute("aria-pressed", String(state.topic === t));
    b.addEventListener("click", () => { state.topic = state.topic === t ? "" : t; renderTopics(); renderFeed(); });
    return b;
  });
  $("#topics").replaceChildren(...chips);
}

function renderSaved() {
  const items = Object.values(state.prefs.saved).sort((a, b) => b.published.localeCompare(a.published));
  $("#saved-count").textContent = items.length ? `(${items.length})` : "";
  const list = $("#saved-list");
  list.replaceChildren(...items.map(articleNode));
  if (!items.length) list.innerHTML = '<li class="empty">Saved articles show up here.</li>';
}

function el(tag, text) {
  const n = document.createElement(tag);
  if (text) n.textContent = text;
  return n;
}

function renderProjects() {
  const data = state.projects;
  if (!data) return;
  $("#projects-intro").textContent = data.projects.length
    ? `Ideas generated ${fmtDate(data.generated_at)} from this week's trending repos and articles.`
    : "No project ideas yet. They're generated weekly when an Anthropic API key is configured.";

  $("#project-list").replaceChildren(...data.projects.map((p) => {
    const card = el("article");
    card.className = "project";
    card.append(el("h3", p.title), el("p", p.pitch));
    const meta = el("div");
    meta.className = "meta";
    meta.append(el("span", `Scope: ${p.scope}`));
    if (p.inspired_by) {
      const a = el("a", "Inspired by");
      a.href = p.inspired_by;
      a.target = "_blank";
      a.rel = "noopener";
      meta.append(el("span", "·"), a);
    }
    const stack = el("div");
    stack.className = "stack";
    stack.append(...p.stack.map((s) => el("span", s)));
    const learn = el("ul");
    learn.append(...p.you_will_learn.map((s) => el("li", s)));
    const steps = el("ol");
    steps.append(...p.milestones.map((s) => el("li", s)));
    card.append(meta, el("h4", "Stack"), stack, el("h4", "You'll learn"), learn, el("h4", "Milestones"), steps);
    return card;
  }));

  $("#trending-list").replaceChildren(...(data.trending || []).map((r) => {
    const li = el("li");
    li.className = "card";
    const meta = el("div", `★ ${r.stars.toLocaleString()}${r.language ? " · " + r.language : ""}`);
    meta.className = "meta";
    const h = el("h3");
    const a = el("a", r.name);
    a.href = r.url;
    a.target = "_blank";
    a.rel = "noopener";
    h.append(a);
    li.append(meta, h, el("p", r.description));
    li.lastChild.className = "summary";
    return li;
  }));
}

function render() {
  renderFeed();
  renderSaved();
}

// ---------- wiring ----------
function setupTabs() {
  const tabs = document.querySelectorAll(".tabs button");
  const show = (name) => {
    tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== name));
    try { localStorage.setItem("reading-tab", name); } catch { /* ignore */ }
  };
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.tab)));
  let last = null;
  try { last = localStorage.getItem("reading-tab"); } catch { /* ignore */ }
  if (last && document.getElementById(last)) show(last);
}

async function init() {
  setupTabs();
  $("#hide-read").checked = state.prefs.hideRead;
  $("#hide-read").addEventListener("change", (e) => { state.prefs.hideRead = e.target.checked; savePrefs(); renderFeed(); });
  for (const id of ["#search", "#kind", "#level"]) $(id).addEventListener("input", renderFeed);

  const [latest, projects] = await Promise.all([fetchJSON("latest.json"), fetchJSON("projects.json")]);
  state.items = latest?.items || [];
  state.projects = projects;

  $("#updated").textContent = latest?.generated_at
    ? `${state.items.length} articles · updated ${fmtDate(latest.generated_at)}`
    : "No data yet. Run the pipeline to fetch articles.";

  const kinds = [...new Set(state.items.map((i) => i.kind).filter((k) => k && k !== "other"))].sort();
  for (const k of kinds) $("#kind").append(new Option(k, k));

  renderTopics();
  renderProjects();
  render();
}

init();
