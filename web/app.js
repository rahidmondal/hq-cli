"use strict";
// hq v2 browser app. Reads /api/state; every change is POST /api/cmd, which
// runs the same hq command the terminal would (logged as by: web).

const TOKEN = document.querySelector('meta[name="hq-token"]').content;
const main = document.getElementById("main");
const drawer = document.getElementById("drawer");
const scrim = document.getElementById("scrim");
const dialog = document.getElementById("dialog");
const toastEl = document.getElementById("toast");

const PAGES = { "/": "today", "/today": "today", "/board": "board", "/goals": "goals" };
const PATHS = { today: "/", board: "/board", goals: "/goals" };
const KINDS = ["task", "bug", "presentation"];
const DAY_MINUTES = 480;

const S = {
  data: null,
  page: PAGES[location.pathname] || "today",
  area: localStorage.getItem("hq.area") || "",
  q: "",
  sel: -1,
  drawer: null, // {project, slug} or {goal}
  free: null, // {minutes, items}
};

// ---- helpers --------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const enc = encodeURIComponent;
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const inArea = (r) => !S.area || r.area === S.area;
const prioRank = (p) => Number(String(p).slice(1)) || 3;

function parseISO(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function daysFromToday(iso) {
  return Math.round((parseISO(iso) - parseISO(S.data.today)) / 86400000);
}
function shortDate(iso) {
  return parseISO(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}
function relDue(iso) {
  const n = daysFromToday(iso);
  if (n === 0) return "due today";
  if (n === 1) return "due tomorrow";
  if (n < 0) return n === -1 ? "due yesterday" : `due ${-n} days ago`;
  return n < 7 ? `due ${parseISO(iso).toLocaleDateString(undefined, { weekday: "long" })}` : `due ${shortDate(iso)}`;
}
function fmtMinutes(m) {
  const h = Math.floor(m / 60), r = m % 60;
  return (h ? `${h}h` : "") + (r || !h ? `${r}m` : "");
}
function goalTitle(slug) {
  const g = S.data.goals.find((g) => g.slug === slug);
  return g ? g.title : slug;
}
function searchText(r) {
  return [r.title, r.slug, r.project, r.kind, r.goal, r.area, r.blocked, ...(r.tags || [])].join(" ").toLowerCase();
}
function byPriority(a, b) {
  return prioRank(a.priority) - prioRank(b.priority)
    || (a.due || "9999").localeCompare(b.due || "9999")
    || String(a.created).localeCompare(String(b.created));
}

let toastTimer;
function toast(msg, isErr = false) {
  toastEl.textContent = msg;
  toastEl.className = "toast" + (isErr ? " err" : "");
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.hidden = true), isErr ? 6000 : 2600);
}

// ---- server ---------------------------------------------------------------

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({ error: `server error ${res.status}` }));
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

async function cmd(body, okMsg) {
  let res;
  try {
    res = await fetch("/api/cmd", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-HQ-Token": TOKEN },
      body: JSON.stringify(body),
    });
  } catch {
    toast("Can't reach hq serve. Is it still running?", true);
    return false;
  }
  const out = await res.json().catch(() => ({ ok: false, error: `server error ${res.status}` }));
  if (!out.ok) {
    toast(out.error, true);
    return false;
  }
  if (okMsg) toast(okMsg);
  await refresh();
  return true;
}

async function refresh() {
  try {
    S.data = await getJSON("/api/state");
    const minutes = S.free?.minutes ?? (Number(localStorage.getItem("hq.free")) || 30);
    S.free = { minutes, items: (await getJSON(`/api/free?minutes=${minutes}`)).items };
  } catch (e) {
    toast(e.message, true);
    return;
  }
  render();
  if (S.drawer) await openDrawer(S.drawer, true);
}

const refOf = (el) => {
  const item = el.closest("[data-slug],[data-goal]");
  if (!item) return null;
  return item.dataset.goal ? { goal: item.dataset.goal } : { project: item.dataset.project, slug: item.dataset.slug };
};

// ---- shared pieces ----------------------------------------------------------

function prioSelect(r, extra = "") {
  const opts = S.data.fields.priorities
    .map((p) => `<option value="${p}"${p === r.priority ? " selected" : ""}>${p}</option>`).join("");
  return `<select class="prio ${esc(r.priority)}" data-set="priority" aria-label="Priority" ${extra}>${opts}</select>`;
}

function rowActions(r) {
  if (r.status === "archive") return "";
  if (r.blocked) return `<button class="btn" data-do="unblock">Unblock</button>`;
  const later = `<button class="btn quiet" data-do="tomorrow" title="Plan it for tomorrow">Tomorrow</button>`;
  return r.status === "planning"
    ? `<button class="btn" data-do="start">Start</button>${later}`
    : `<button class="btn" data-do="done">Done</button>${later}`;
}

function row(r, when = "") {
  const late = /ago|yesterday|late/.test(when);
  const sub = [
    `<span class="area ${esc(r.area)}">${esc(r.project)}</span>`,
    r.status === "active" ? `<span class="pill live">In progress</span>` : "",
    r.goal ? `<span class="goalref">${esc(goalTitle(r.goal))}</span>` : "",
    r.blocked ? `<span class="reason">Blocked: ${esc(r.blocked)}</span>` : "",
  ].join("");
  const meta = [
    when ? `<span class="when${late ? " late" : ""}">${esc(when)}</span>` : "",
    r.est_label ? `<span class="est">${esc(r.est_label)}</span>` : "",
  ].join("");
  return `<div class="row item" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}">
    ${prioSelect(r)}
    <div class="main" data-open><div class="title">${esc(r.title)}</div><div class="sub">${sub}</div></div>
    <div class="meta">${meta}</div>
    <div class="acts">${rowActions(r)}</div>
  </div>`;
}

function search(placeholder = "Search") {
  return `<label class="searchwrap"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>
    <input class="search" type="search" placeholder="${esc(placeholder)}" value="${esc(S.q)}" aria-label="Search"><kbd>/</kbd></label>`;
}

function head(title, sub = "", extra = "") {
  return `<header class="head"><div><h1>${esc(title)}</h1>${sub ? `<p class="lede">${sub}</p>` : ""}</div>
    <div class="headtools">${extra}${search()}</div></header>${mobileAreas()}`;
}

function mobileAreas() {
  const b = (v, label) => `<button type="button" aria-pressed="${S.area === v}" data-area="${v}">${label}</button>`;
  return `<div class="mobile-areas areas" role="group" aria-label="Area">${b("", "All")}${b("work", "Work")}${b("personal", "Personal")}</div>`;
}

function plural(n, one, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

// ---- Today ------------------------------------------------------------------

const SECTION_TONE = { due: "rose", planned: "violet", goals: "amber", top: "teal" };

function todayParts() {
  const sections = S.data.sections
    .map((s) => ({ ...s, items: s.items.filter(inArea) }))
    .filter((s) => s.items.length);
  const blocked = sections.find((s) => s.key === "blocked")?.items || [];
  const lists = sections.filter((s) => s.key !== "blocked");
  return { lists, blocked, doing: lists.flatMap((s) => s.items) };
}

function budgetCard(doing, blockedCount) {
  const byP = { P1: 0, P2: 0, P3: 0, P4: 0 };
  let total = 0, noEst = 0;
  for (const r of doing) {
    if (r.est) { byP[r.priority] += r.est; total += r.est; } else noEst++;
  }
  const scale = Math.max(DAY_MINUTES, total);
  const segs = Object.entries(byP).filter(([, m]) => m)
    .map(([p, m]) => `<span class="s-${p}" style="width:${(m / scale) * 100}%" title="${p}: ${fmtMinutes(m)}"></span>`).join("");
  const ticks = Array.from({ length: Math.floor(scale / 60) - 1 }, (_, i) =>
    `<i class="tick" style="left:${(((i + 1) * 60) / scale) * 100}%"></i>`).join("");
  const legend = Object.entries(byP).filter(([, m]) => m)
    .map(([p, m]) => `<span class="lg"><i class="dot ${p}"></i>${p} ${fmtMinutes(m)}</span>`).join("");
  const work = doing.filter((r) => r.area === "work").length;
  const stats = [
    [doing.length, doing.length === 1 ? "to do" : "to do"],
    [work, "work"], [doing.length - work, "personal"], [blockedCount, "blocked"],
  ].map(([n, label]) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`).join("");
  let note = doing.length ? "Everything has an estimate" : "Nothing planned yet";
  if (noEst) note = `${plural(noEst, "task")} without an estimate`;
  if (total > DAY_MINUTES) note += ", more than an 8-hour day";
  return `<section class="budget glass">
    <div class="budget-top">
      <div><div class="budget-total">${total ? fmtMinutes(total) : "No time"} <span>estimated</span></div>
        <div class="budget-note">${note}</div></div>
      <div class="stats">${stats}</div>
    </div>
    <div class="bar" role="img" aria-label="${fmtMinutes(total)} estimated today">${segs}${ticks}</div>
    <div class="legend">${legend || '<span class="lg">Add estimates to see your day fill up</span>'}<span class="lg end">8-hour day</span></div>
  </section>`;
}

function freeCard() {
  const minutes = S.free?.minutes ?? 30;
  const items = (S.free?.items || []).filter(inArea).slice(0, 4);
  const chips = [15, 30, 60, 90].map((m) =>
    `<button type="button" class="chip${m === minutes ? " on" : ""}" data-free="${m}">${fmtMinutes(m)}</button>`).join("");
  const list = items.length
    ? items.map((r) => `<div class="mini item" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}" data-open>
        <i class="dot ${esc(r.priority)}"></i><span class="mtitle">${esc(r.title)}</span><span class="mest">${esc(r.est_label)}</span></div>`).join("")
    : `<p class="quiet">Nothing with an estimate fits in ${esc(fmtMinutes(minutes))}. Set estimates in a task's details.</p>`;
  return `<section class="side-card glass">
    <h3>I've got time</h3>
    <form class="chips" data-form="free">${chips}
      <input name="minutes" type="number" min="5" step="5" placeholder="Other" value="${[15, 30, 60, 90].includes(minutes) ? "" : minutes}"
        class="${[15, 30, 60, 90].includes(minutes) ? "" : "on"}" aria-label="Other amount, in minutes" title="Other amount, in minutes"></form>
    <div class="minis">${list}</div>
  </section>`;
}

function targetLabel(iso) {
  const n = daysFromToday(iso);
  return n === 0 ? "due today" : n > 0 ? `in ${n}d` : `${-n}d late`;
}

function goalsCard() {
  const goals = S.data.goals.filter((g) => g.status === "active" && inArea(g))
    .sort((a, b) => (a.target || "9999").localeCompare(b.target || "9999")).slice(0, 4);
  if (!goals.length) return "";
  return `<section class="side-card glass"><h3>Goals<a class="more" href="/goals" data-nav="goals">All goals</a></h3>
    ${goals.map((g) => {
      const total = g.open + g.done;
      const pct = total ? Math.round((g.done / total) * 100) : 0;
      return `<div class="mini goalmini" data-goal="${esc(g.slug)}" data-open>
        <div class="gm-top"><span class="mtitle">${esc(g.title)}</span><span class="mest">${g.target ? esc(targetLabel(g.target)) : ""}</span></div>
        <div class="progress"><span class="done" style="width:${pct}%"></span></div></div>`;
    }).join("")}</section>`;
}

function blockedCard(blocked) {
  if (!blocked.length) return "";
  return `<section class="side-card glass blocked-card"><h3>Blocked<span class="count">${blocked.length}</span></h3>
    ${blocked.map((r) => `<div class="mini item" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}">
      <div class="bm" data-open><span class="mtitle">${esc(r.title)}</span><span class="reason">${esc(r.blocked)}</span></div>
      <button class="btn small" data-do="unblock">Unblock</button></div>`).join("")}</section>`;
}

function renderToday() {
  const day = parseISO(S.data.today);
  const { lists, blocked, doing } = todayParts();
  let listHtml = "";
  if (!lists.length) {
    listHtml = `<div class="empty-state glass"><strong>Nothing due or planned today.</strong>
      <p>Today fills itself from due dates, do-on dates, goal deadlines and active P1 and P2 work. Give a task a date or a priority, or add one.</p>
      <div class="empty-actions"><button class="btn primary" data-act="new-task">New task</button>
      <a class="btn" href="/board" data-nav="board">Open the board</a></div></div>`;
  }
  for (const s of lists) {
    listHtml += `<section class="section glass tone-${SECTION_TONE[s.key] || "violet"}" data-section="${esc(s.key)}">
      <h2><i class="marker"></i>${esc(s.title)}<span class="count">${s.items.length}</span></h2>
      ${s.items.map((r) => row(r, r.when)).join("")}</section>`;
  }
  return `<div class="page today">
    <header class="hero">
      <div><div class="weekday">${esc(day.toLocaleDateString(undefined, { weekday: "long" }))}</div>
        <h1 class="date">${esc(day.toLocaleDateString(undefined, { day: "numeric", month: "long" }))}</h1></div>
      <div class="headtools">${search("Search today")}</div>
    </header>
    ${mobileAreas()}
    ${budgetCard(doing, blocked.length)}
    <div class="today-grid">
      <div class="today-main">${listHtml}</div>
      <aside class="today-side">${freeCard()}${goalsCard()}${blockedCard(blocked)}</aside>
    </div>
  </div>`;
}

// ---- Board ------------------------------------------------------------------

function card(r) {
  const bits = [
    `<span class="tag-prio ${esc(r.priority)}">${esc(r.priority)}</span>`,
    `<span class="area ${esc(r.area)}">${esc(r.area)}</span>`,
    r.due && r.status !== "archive" ? `<span${daysFromToday(r.due) < 0 ? ' class="reason"' : ""}>${esc(relDue(r.due))}</span>` : "",
    r.est_label ? `<span>${esc(r.est_label)}</span>` : "",
    r.kind && r.kind !== "task" ? `<span class="kind">${esc(r.kind)}</span>` : "",
    r.outcome === "dropped" ? "<span>dropped</span>" : "",
  ].join("");
  const cls = (r.blocked ? " blocked" : "") + (r.outcome === "dropped" ? " dropped" : "");
  const reason = r.blocked ? `<div class="reason cardreason">Blocked: ${esc(r.blocked)}</div>` : "";
  return `<div class="card item${cls}" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}" data-open tabindex="-1">
    <div class="title">${esc(r.title)}</div>${reason}<div class="sub">${bits}</div></div>`;
}

function renderBoard() {
  const entries = S.data.entries.filter(inArea);
  const projects = [...new Set(entries.map((r) => r.project))].sort();
  const open = entries.filter((r) => r.status !== "archive").length;
  const lede = `${plural(open, "open entry", "open entries")} across ${plural(projects.length, "project")}. Drag a card to move it.`;
  let html = `<div class="page wide">${head("Board", lede)}`;
  if (!projects.length) html += `<div class="empty-state glass"><strong>No entries${S.area ? ` in ${esc(S.area)}` : ""}.</strong></div>`;
  for (const p of projects) {
    const mine = entries.filter((r) => r.project === p);
    const count = (st) => mine.filter((r) => r.status === st).length;
    const col = (status, label) => {
      const rows = mine.filter((r) => r.status === status).sort(status === "archive"
        ? (a, b) => String(b.created).localeCompare(String(a.created)) : byPriority);
      const cards = rows.map(card).join("") || `<div class="dropzone">${status === "archive" ? "Nothing archived" : "Drop a card here"}</div>`;
      const h = `<i class="coldot"></i>${label}<span class="count">${rows.length}</span>`;
      return status === "archive"
        ? `<details class="col archive" data-drop="archive" data-project="${esc(p)}"><summary>${h}<span class="toggle"></span></summary>${cards}</details>`
        : `<div class="col ${status}" data-drop="${status}" data-project="${esc(p)}"><h3>${h}</h3>${cards}</div>`;
    };
    const area = S.data.projects.find((x) => x.name === p)?.area || "work";
    html += `<section class="project glass"><header class="projhead"><h2><span class="area ${esc(area)}"></span>${esc(p)}</h2>
      <span class="projnums">${count("planning")} planned, ${count("active")} in progress, ${count("archive")} archived</span></header>
      <div class="board">${col("planning", "Planning")}${col("active", "In progress")}${col("archive", "Archive")}</div></section>`;
  }
  return html + "</div>";
}

// ---- Goals ------------------------------------------------------------------

function goalCard(g) {
  const total = g.open + g.done + g.dropped;
  const pct = (n) => (total ? (n / total) * 100 : 0);
  const donePct = g.open + g.done ? Math.round((g.done / (g.open + g.done)) * 100) : 0;
  let target = "No target date", cls = "";
  if (g.target) {
    const n = daysFromToday(g.target);
    target = n === 0 ? "Due today" : n > 0 ? `Due in ${plural(n, "day")}` : `${plural(-n, "day")} late`;
    cls = n < 0 ? "late" : n <= 7 ? "soon" : "";
  }
  if (g.status !== "active") { target = g.status === "done" ? "Done" : "Dropped"; cls = "closed"; }
  const nums = total
    ? `${g.done} of ${g.open + g.done} done${g.blocked ? `, ${g.blocked} blocked` : ""}${g.dropped ? `, ${g.dropped} dropped` : ""}`
    : "No tasks yet";
  return `<article class="goalcard glass item${g.status !== "active" ? " closed" : ""}" data-goal="${esc(g.slug)}" data-t="${esc((g.title + " " + g.slug + " " + g.area).toLowerCase())}" data-open tabindex="-1">
    <div class="gc-top"><span class="tag-prio ${esc(g.priority)}">${esc(g.priority)}</span><span class="area ${esc(g.area)}">${esc(g.area)}</span>
      <span class="target ${cls}">${esc(target)}</span></div>
    <h3>${esc(g.title)}</h3>
    <div class="gc-progress"><div class="progress"><span class="done" style="width:${pct(g.done)}%"></span><span class="dropped" style="width:${pct(g.dropped)}%"></span></div>
      <b>${donePct}%</b></div>
    <div class="gc-foot"><span>${esc(nums)}</span>${g.target ? `<span>${esc(shortDate(g.target))}</span>` : ""}</div>
  </article>`;
}

function renderGoals() {
  const goals = S.data.goals.filter(inArea);
  const active = goals.filter((g) => g.status === "active").sort((a, b) =>
    prioRank(a.priority) - prioRank(b.priority) || (a.target || "9999").localeCompare(b.target || "9999"));
  const closed = goals.filter((g) => g.status !== "active");
  let html = `<div class="page">${head("Goals", "Goals group tasks across projects. Tasks in a goal due within a week show up on Today.",
    `<button class="btn primary" data-act="new-goal">New goal</button>`)}`;
  if (!goals.length) {
    html += `<div class="empty-state glass"><strong>No goals yet.</strong>
      <p>Create one, then pick it in a task's details.</p>
      <div class="empty-actions"><button class="btn primary" data-act="new-goal">New goal</button></div></div>`;
  }
  if (active.length) html += `<h2 class="group-title">Active<span class="count">${active.length}</span></h2><div class="goalgrid">${active.map(goalCard).join("")}</div>`;
  if (closed.length) html += `<h2 class="group-title">Closed<span class="count">${closed.length}</span></h2><div class="goalgrid">${closed.map(goalCard).join("")}</div>`;
  return html + "</div>";
}

// ---- render + search ----------------------------------------------------------

function render() {
  if (!S.data) return;
  const html = { today: renderToday, board: renderBoard, goals: renderGoals }[S.page]();
  main.innerHTML = html;
  $$(".navlink").forEach((a) => (a.dataset.nav === S.page
    ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  $$(".areas button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.area === S.area)));
  const counts = {
    today: todayParts().doing.length,
    board: S.data.entries.filter((r) => r.status !== "archive" && inArea(r)).length,
    goals: S.data.goals.filter((g) => g.status === "active" && inArea(g)).length,
  };
  $$("[data-count]").forEach((el) => (el.textContent = counts[el.dataset.count] || ""));
  applySearch();
  select(S.sel, false);
}

function applySearch() {
  const q = S.q.trim().toLowerCase();
  $$(".item", main).forEach((el) => (el.hidden = !!q && !(el.dataset.t || "").includes(q)));
  $$(".section, .project, .side-card", main).forEach((sec) => {
    sec.hidden = !!q && !sec.querySelector(".item:not([hidden])");
  });
  $$("details.col", main).forEach((d) => { if (q && d.querySelector(".item:not([hidden])")) d.open = true; });
}

function visibleItems() {
  return $$(".item", main).filter((el) => !el.hidden && el.offsetParent !== null);
}

function select(i, scroll = true) {
  const items = visibleItems();
  $$(".sel", main).forEach((el) => el.classList.remove("sel"));
  if (!items.length || i < 0) { S.sel = -1; return; }
  S.sel = Math.min(i, items.length - 1);
  const el = items[S.sel];
  el.classList.add("sel");
  if (scroll) el.scrollIntoView({ block: "nearest" });
}

function go(page) {
  if (!PATHS[page]) return;
  S.page = page;
  S.sel = -1;
  if (location.pathname !== PATHS[page]) history.pushState(null, "", PATHS[page]);
  render();
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---- drawer -------------------------------------------------------------------

const ACTION_TEXT = {
  save: () => "created", start: () => "started", unstart: () => "moved back to planning",
  archive: (l) => (l.outcome === "dropped" ? "dropped" : "marked done"),
  block: (l) => `blocked: ${l.reason}`, unblock: () => "unblocked", note: (l) => l.text,
  set: (l) => (l.to == null ? `cleared ${l.field}` : `set ${l.field} to ${l.to}`),
  goal: (l) => ({ new: "created", done: "marked done", dropped: "dropped" }[l.op] || l.op),
};

function logList(lines) {
  if (!lines.length) return `<p class="sub" style="color:var(--muted)">No activity yet.</p>`;
  return `<ul class="log">${[...lines].reverse().map((l) => {
    const text = (ACTION_TEXT[l.action] || (() => l.action))(l);
    const by = l.by && l.by !== "user" ? `<span class="by-${esc(l.by)}">${esc(l.by)}</span> ` : "";
    return `<li><span>${esc(l.local)}</span><span>${by}${esc(text)}</span></li>`;
  }).join("")}</ul>`;
}

function selectCtl(name, options, value, extra = "") {
  return `<select data-set="${name}" ${extra}>${options.map(([v, label]) =>
    `<option value="${esc(v)}"${v === (value ?? "") ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
}

function entryDrawer(e) {
  const r = e.record;
  const goals = S.data.goals.filter((g) => g.status === "active" || g.slug === r.goal);
  const isOpen = r.status !== "archive";
  const dis = isOpen ? "" : "disabled";
  const statusText = { planning: "Planning", active: "In progress", archive: r.outcome === "dropped" ? "Dropped" : "Done" }[r.status];
  const actions = !isOpen ? "" : [
    r.status === "planning" ? `<button class="btn primary" data-do="start">Start</button>` : `<button class="btn primary" data-do="done">Done</button>`,
    r.status === "planning" ? `<button class="btn" data-do="done">Done</button>` : `<button class="btn" data-do="unstart">Back to planning</button>`,
    r.blocked ? `<button class="btn" data-do="unblock">Unblock</button>` : `<button class="btn" data-do="show-block">Block</button>`,
    `<button class="btn danger" data-do="drop">Drop</button>`,
  ].join("");
  const folder = r.href.replace(/README\.md$/, "");
  const files = e.files.length ? `<h3>Files</h3><div class="sub" style="display:flex;flex-wrap:wrap;gap:.3rem .8rem">${e.files
    .map((f) => `<a class="fullpage" href="${esc(folder + enc(f))}" target="_blank" rel="noopener">${esc(f)}</a>`).join("")}</div>` : "";
  return `<div data-project="${esc(r.project)}" data-slug="${esc(r.slug)}">
    <div class="top"><h2>${esc(r.title)}</h2><button class="btn quiet" data-do="close" aria-label="Close">Close</button></div>
    <div class="where">${esc(r.project)}, ${esc(statusText)}${r.kind && r.kind !== "task" ? `, ${esc(r.kind)}` : ""}, created ${esc(r.created)}</div>
    ${r.blocked ? `<div class="banner blocked">Blocked: ${esc(r.blocked)}</div>` : ""}
    <div class="fields">
      <div class="field"><label>Priority</label>${selectCtl("priority", S.data.fields.priorities.map((p) => [p, p]), r.priority, dis)}</div>
      <div class="field"><label>Area</label>${selectCtl("area", S.data.fields.areas.map((a) => [a, a[0].toUpperCase() + a.slice(1)]), r.area, dis)}</div>
      <div class="field"><label>Estimate</label><input data-set="est" value="${esc(r.est_label || "")}" placeholder="e.g. 45m or 1h30m" ${dis}></div>
      <div class="field"><label>Due</label><input type="date" data-set="due" value="${esc(r.due || "")}" ${dis}></div>
      <div class="field"><label>Do on</label><input type="date" data-set="do-on" value="${esc(r.do_on || "")}" ${dis}></div>
      <div class="field"><label>Goal</label>${selectCtl("goal", [["", "None"], ...goals.map((g) => [g.slug, g.title])], r.goal, dis)}</div>
    </div>
    <div class="actions">${actions}</div>
    <form class="blockbox" data-form="block" hidden><input name="reason" placeholder="What is it waiting on?" required><button class="btn primary">Block</button></form>
    <form class="notebox" data-form="note"><input name="text" placeholder="Add a note to the log" required><button class="btn">Add note</button></form>
    <h3>Activity</h3>${logList(e.log)}
    ${files}
    <h3>Notes</h3><div class="md"></div>
    <p><a class="fullpage" href="${esc(r.href)}" target="_blank" rel="noopener">Open the full page</a></p>
  </div>`;
}

function goalDrawer(e) {
  const g = e.record;
  const isOpen = g.status === "active";
  const dis = isOpen ? "" : "disabled";
  const tasks = (e.tasks || []).slice().sort((a, b) => ["active", "planning", "archive"].indexOf(a.status) - ["active", "planning", "archive"].indexOf(b.status));
  return `<div data-goal="${esc(g.slug)}">
    <div class="top"><h2>${esc(g.title)}</h2><button class="btn quiet" data-do="close" aria-label="Close">Close</button></div>
    <div class="where">Goal, ${esc(g.status)}, created ${esc(g.created)}</div>
    <div class="fields">
      <div class="field"><label>Priority</label>${selectCtl("priority", S.data.fields.priorities.map((p) => [p, p]), g.priority, dis)}</div>
      <div class="field"><label>Area</label>${selectCtl("area", S.data.fields.areas.map((a) => [a, a[0].toUpperCase() + a.slice(1)]), g.area, dis)}</div>
      <div class="field"><label>Target</label><input type="date" data-set="target" value="${esc(g.target || "")}" ${dis}></div>
    </div>
    <div class="actions">${isOpen ? `<button class="btn primary" data-do="goal-done">Mark goal done</button><button class="btn danger" data-do="goal-drop">Drop goal</button>
      <button class="btn" data-act="new-task" data-goal-default="${esc(g.slug)}">Add a task to this goal</button>` : ""}</div>
    <h3>Tasks</h3>
    <div class="tasklist">${tasks.length ? tasks.map((t) => {
      const full = S.data.entries.find((r) => r.project === t.project && r.slug === t.slug);
      return full ? row(full, full.status === "archive" ? (full.outcome === "dropped" ? "dropped" : "done") : full.due ? relDue(full.due) : "") : "";
    }).join("") : `<p class="sub" style="color:var(--muted)">No tasks in this goal yet. Pick this goal in a task's details, or add one here.</p>`}</div>
    <form class="notebox" data-form="note" style="margin-top:1.2rem"><input name="text" placeholder="Add a note to the log" required><button class="btn">Add note</button></form>
    <h3>Activity</h3>${logList(e.log)}
    <h3>Notes</h3><div class="md"></div>
  </div>`;
}

async function openDrawer(ref, quiet = false) {
  const q = ref.goal ? `goal=${enc(ref.goal)}` : `project=${enc(ref.project)}&slug=${enc(ref.slug)}`;
  let e;
  try {
    e = await getJSON(`/api/entry?${q}`);
  } catch (err) {
    if (!quiet) toast(err.message, true);
    closeDrawer();
    return;
  }
  const scrollTop = drawer.scrollTop;
  S.drawer = ref;
  drawer.innerHTML = ref.goal ? goalDrawer(e) : entryDrawer(e);
  const md = drawer.querySelector(".md");
  if (md && window.marked) md.innerHTML = e.body.trim() ? marked.parse(e.body) : `<p style="color:var(--muted)">No notes in this file.</p>`;
  drawer.hidden = false;
  scrim.hidden = false;
  if (quiet) drawer.scrollTop = scrollTop;
  else drawer.querySelector("[data-do=close]")?.focus();
}

function closeDrawer() {
  S.drawer = null;
  drawer.hidden = true;
  scrim.hidden = true;
  drawer.innerHTML = "";
}

// ---- dialogs ------------------------------------------------------------------

function openNewTask(goalDefault = "") {
  const d = S.data;
  const last = localStorage.getItem("hq.project") || d.projects[0]?.name || "";
  const goals = d.goals.filter((g) => g.status === "active");
  dialog.innerHTML = `<form method="dialog" data-form="new-task">
    <h2>New task</h2>
    <input class="titlein" name="title" placeholder="What needs doing?" required autocomplete="off">
    <div class="fields">
      <div class="field"><label>Project</label><input name="project" list="projlist" value="${esc(last)}" required></div>
      <div class="field"><label>Kind</label>${selectCtl("kind", KINDS.map((k) => [k, k[0].toUpperCase() + k.slice(1)]), "task", 'name="kind"')}</div>
      <div class="field"><label>Priority</label>${selectCtl("priority", d.fields.priorities.map((p) => [p, p]), "P3", 'name="priority"')}</div>
      <div class="field"><label>Due</label><input type="date" name="due"></div>
      <div class="field"><label>Do on</label><input type="date" name="do_on" value="${S.page === "today" ? esc(d.today) : ""}"></div>
      <div class="field"><label>Estimate</label><input name="est" placeholder="e.g. 30m"></div>
      <div class="field"><label>Area</label>${selectCtl("area", [["", "Project default"], ...d.fields.areas.map((a) => [a, a[0].toUpperCase() + a.slice(1)])], S.area, 'name="area"')}</div>
      <div class="field" style="grid-column:span 2"><label>Goal</label>${selectCtl("goal_ref", [["", "None"], ...goals.map((g) => [g.slug, g.title])], goalDefault, 'name="goal_ref"')}</div>
    </div>
    <datalist id="projlist">${d.projects.map((p) => `<option value="${esc(p.name)}">`).join("")}</datalist>
    <p class="err"></p>
    <div class="foot"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="save">Save task</button></div>
  </form>`;
  dialog.showModal();
  dialog.querySelector("[name=title]").focus();
}

function openNewGoal() {
  const d = S.data;
  dialog.innerHTML = `<form method="dialog" data-form="new-goal">
    <h2>New goal</h2>
    <input class="titlein" name="title" placeholder="What are you working towards?" required autocomplete="off">
    <div class="fields">
      <div class="field"><label>Area</label>${selectCtl("area", d.fields.areas.map((a) => [a, a[0].toUpperCase() + a.slice(1)]), S.area || "work", 'name="area"')}</div>
      <div class="field"><label>Priority</label>${selectCtl("priority", d.fields.priorities.map((p) => [p, p]), "P2", 'name="priority"')}</div>
      <div class="field"><label>Target date</label><input type="date" name="target"></div>
    </div>
    <p class="err"></p>
    <div class="foot"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="save">Create goal</button></div>
  </form>`;
  dialog.showModal();
  dialog.querySelector("[name=title]").focus();
}

dialog.addEventListener("submit", async (ev) => {
  const form = ev.target;
  if (ev.submitter?.value === "cancel") return; // let the dialog close
  ev.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const err = form.querySelector(".err");
  let ok;
  if (form.dataset.form === "new-task") {
    localStorage.setItem("hq.project", data.project);
    ok = await cmd({ action: "save", ...data }, "Task saved");
  } else {
    ok = await cmd({ action: "goal_new", ...data }, "Goal created");
  }
  if (ok) dialog.close();
  else err.textContent = toastEl.textContent;
});

// ---- events -------------------------------------------------------------------

function setFree(value) {
  const minutes = Math.max(5, Math.round(Number(value) || 30));
  localStorage.setItem("hq.free", String(minutes));
  getJSON(`/api/free?minutes=${minutes}`).then((r) => { S.free = { minutes, items: r.items }; render(); })
    .catch((e) => toast(e.message, true));
}

async function doAction(what, ref) {
  const base = ref.goal ? { goal: ref.goal } : { project: ref.project, slug: ref.slug };
  switch (what) {
    case "start": return cmd({ action: "start", ...base }, "Started");
    case "done": return cmd({ action: "archive", ...base }, "Marked done");
    case "drop":
      if (!confirm("Drop this entry? It moves to the archive as dropped.")) return;
      return cmd({ action: "archive", dropped: true, ...base }, "Dropped");
    case "unstart": return cmd({ action: "unstart", ...base }, "Moved back to planning");
    case "unblock": return cmd({ action: "unblock", ...base }, "Unblocked");
    case "tomorrow": return cmd({ action: "set", field: "do-on", value: "tomorrow", ...base }, "Planned for tomorrow");
    case "goal-done": return cmd({ action: "goal_done", goal: ref.goal }, "Goal marked done");
    case "goal-drop":
      if (!confirm("Drop this goal?")) return;
      return cmd({ action: "goal_done", goal: ref.goal, dropped: true }, "Goal dropped");
  }
}

document.addEventListener("click", (ev) => {
  if (drag.justDropped) { drag.justDropped = false; ev.preventDefault(); return; }
  const t = ev.target;
  const nav = t.closest("[data-nav]");
  if (nav && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); closeDrawer(); return go(nav.dataset.nav); }
  const area = t.closest("[data-area]");
  if (area) {
    S.area = area.dataset.area;
    localStorage.setItem("hq.area", S.area);
    S.sel = -1;
    return render();
  }
  const chip = t.closest("[data-free]");
  if (chip) return setFree(chip.dataset.free);
  const act = t.closest("[data-act]");
  if (act) {
    if (act.dataset.act === "new-task") return openNewTask(act.dataset.goalDefault || "");
    if (act.dataset.act === "new-goal") return openNewGoal();
  }
  const btn = t.closest("[data-do]");
  if (btn) {
    const what = btn.dataset.do;
    if (what === "close") return closeDrawer();
    if (what === "show-block") {
      const box = drawer.querySelector("[data-form=block]");
      box.hidden = false;
      return box.querySelector("input").focus();
    }
    const ref = refOf(btn);
    if (ref) return doAction(what, ref);
  }
  if (t.closest("select, input, a, button")) return;
  const open = t.closest("[data-open]");
  if (open) {
    const ref = refOf(open);
    if (ref) {
      const items = visibleItems();
      const item = open.closest(".item");
      if (item && main.contains(item)) select(items.indexOf(item), false);
      openDrawer(ref);
    }
  }
});
scrim.addEventListener("click", closeDrawer);

document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (!el.dataset.set || dialog.contains(el)) return;
  const ref = refOf(el);
  if (!ref) return;
  const field = el.dataset.set;
  const value = el.value.trim() || "none";
  const label = field === "do-on" ? "Do-on date" : field[0].toUpperCase() + field.slice(1);
  cmd({ action: "set", field, value, ...(ref.goal ? { goal: ref.goal } : ref) },
    value === "none" ? `${label} cleared` : `${label} set`);
});

document.addEventListener("submit", (ev) => {
  const form = ev.target;
  if (dialog.contains(form)) return;
  ev.preventDefault();
  const kind = form.dataset.form;
  if (kind === "free") return setFree(form.minutes.value);
  const ref = refOf(form);
  if (!ref) return;
  const base = ref.goal ? { goal: ref.goal } : ref;
  if (kind === "block") cmd({ action: "block", reason: form.reason.value, ...base }, "Blocked");
  if (kind === "note") cmd({ action: "note", text: form.text.value, ...base }, "Note added");
});

document.addEventListener("input", (ev) => {
  if (!ev.target.classList.contains("search")) return;
  S.q = ev.target.value;
  applySearch();
  select(-1);
});

document.addEventListener("keydown", (ev) => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey || dialog.open) return;
  const typing = !!ev.target.matches?.("input, select, textarea");
  if (ev.key === "Escape") {
    if (typing) return ev.target.blur();
    if (S.drawer) return closeDrawer();
    if (S.q) { S.q = ""; return render(); }
    return;
  }
  if (typing) return;
  const keys = {
    "/": () => {
      const box = main.querySelector(".search");
      box.focus();
      box.select();
    },
    n: () => openNewTask(),
    t: () => { closeDrawer(); go("today"); },
    b: () => { closeDrawer(); go("board"); },
    g: () => { closeDrawer(); go("goals"); },
    j: () => select(S.sel + 1),
    k: () => select(Math.max(0, S.sel - 1)),
    e: () => openSelected(),
    Enter: () => openSelected(),
  };
  if (keys[ev.key]) { ev.preventDefault(); keys[ev.key](); }
});

function openSelected() {
  const el = visibleItems()[S.sel];
  const ref = el && refOf(el);
  if (ref) openDrawer(ref);
}

addEventListener("popstate", () => {
  S.page = PAGES[location.pathname] || "today";
  closeDrawer();
  render();
});

// Agents and the terminal change things too: refresh when you come back to the
// tab, and every minute while it's visible and you're not mid-edit.
function idle() {
  return !dialog.open && !document.activeElement?.matches("input, select, textarea");
}
addEventListener("focus", () => idle() && refresh());
setInterval(() => document.visibilityState === "visible" && idle() && refresh(), 60000);

refresh();

// ---- drag and drop on the Board ----------------------------------------------
// Pointer events (not HTML5 drag and drop) so it works with a mouse and touch.
// A card moves only within its own project:
//   planning -> active: start    active -> planning: unstart
//   planning/active -> archive: archive (done)
// Archived cards can't be dragged: hq has no command to un-archive.

const MOVES = {
  "planning>active": { action: "start", msg: "Started" },
  "active>planning": { action: "unstart", msg: "Moved back to planning" },
  "planning>archive": { action: "archive", msg: "Marked done" },
  "active>archive": { action: "archive", msg: "Marked done" },
};
const drag = { card: null, ghost: null, from: null, startX: 0, startY: 0, active: false, over: null, justDropped: false,
  touch: false, timer: 0 };
const LONG_PRESS_MS = 350;

function dropTarget(x, y) {
  const el = document.elementFromPoint(x, y);
  const col = el && el.closest("[data-drop]");
  if (!col || col.dataset.project !== drag.card.dataset.project) return null;
  return col;
}

function startDrag() {
  drag.active = true;
  const r = drag.card.getBoundingClientRect();
  drag.ghost = drag.card.cloneNode(true);
  drag.ghost.classList.add("drag-ghost");
  drag.ghost.style.width = `${r.width}px`;
  drag.offX = drag.startX - r.left;
  drag.offY = drag.startY - r.top;
  drag.ghost.style.transform = `translate(${r.left}px, ${r.top}px) rotate(1.5deg)`;
  document.body.appendChild(drag.ghost);
  drag.card.classList.add("dragging");
  document.body.classList.add("is-dragging");
  if (drag.touch) navigator.vibrate?.(15);
}

function endDrag() {
  clearTimeout(drag.timer);
  drag.ghost?.remove();
  drag.card?.classList.remove("dragging");
  drag.over?.classList.remove("drop-ok", "drop-no");
  document.body.classList.remove("is-dragging");
  Object.assign(drag, { card: null, ghost: null, from: null, active: false, over: null });
}

main.addEventListener("pointerdown", (ev) => {
  if (S.page !== "board" || ev.button !== 0) return;
  const card = ev.target.closest(".card");
  const col = card && card.closest("[data-drop]");
  if (!card || !col || col.dataset.drop === "archive") return;
  const touch = ev.pointerType !== "mouse";
  Object.assign(drag, { card, from: col.dataset.drop, startX: ev.clientX, startY: ev.clientY, active: false, touch });
  // Touch: a long press picks the card up, so a normal swipe still scrolls.
  if (touch) drag.timer = setTimeout(() => drag.card && startDrag(), LONG_PRESS_MS);
});

addEventListener("pointermove", (ev) => {
  if (!drag.card) return;
  if (!drag.active) {
    const moved = Math.hypot(ev.clientX - drag.startX, ev.clientY - drag.startY);
    if (drag.touch) { if (moved > 8) endDrag(); return; } // scrolling, not dragging
    if (moved < 6) return;
    startDrag();
  }
  ev.preventDefault();
  drag.ghost.style.transform = `translate(${ev.clientX - drag.offX}px, ${ev.clientY - drag.offY}px) rotate(1.5deg)`;
  const col = dropTarget(ev.clientX, ev.clientY);
  if (col !== drag.over) {
    drag.over?.classList.remove("drop-ok", "drop-no");
    drag.over = col;
    if (col && col.dataset.drop !== drag.from) {
      col.classList.add(MOVES[`${drag.from}>${col.dataset.drop}`] ? "drop-ok" : "drop-no");
    }
  }
}, { passive: false });

addEventListener("pointerup", async (ev) => {
  if (!drag.card) return;
  if (!drag.active) { endDrag(); return; } // a plain click: let it open the details
  drag.justDropped = true;
  setTimeout(() => (drag.justDropped = false), 50);
  const col = dropTarget(ev.clientX, ev.clientY);
  const move = col && MOVES[`${drag.from}>${col.dataset.drop}`];
  const ref = { project: drag.card.dataset.project, slug: drag.card.dataset.slug };
  if (col && col.dataset.drop !== drag.from && !move) toast("That move isn't possible", true);
  const under = document.elementFromPoint(ev.clientX, ev.clientY)?.closest("[data-drop]");
  if (!col && under && under.dataset.project !== ref.project) toast("Cards can only move within their own project", true);
  endDrag();
  if (move) await cmd({ action: move.action, ...ref }, move.msg);
});

addEventListener("pointercancel", endDrag);
// Once a touch drag is live, stop the page from scrolling under the finger.
addEventListener("touchmove", (ev) => { if (drag.active) ev.preventDefault(); }, { passive: false });
main.addEventListener("contextmenu", (ev) => { if (drag.card) ev.preventDefault(); });
addEventListener("keydown", (ev) => { if (ev.key === "Escape" && drag.active) { drag.justDropped = true; endDrag(); } }, true);
