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
    if (S.free) S.free.items = (await getJSON(`/api/free?minutes=${S.free.minutes}`)).items;
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
    r.status === "active" ? `<span class="status-active">in progress</span>` : "",
    r.goal ? `<span>${esc(goalTitle(r.goal))}</span>` : "",
    r.blocked ? `<span class="reason">Blocked: ${esc(r.blocked)}</span>` : "",
  ].join("");
  return `<div class="row item" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}">
    ${prioSelect(r)}
    <div class="main" data-open><div class="title">${esc(r.title)}</div><div class="sub">${sub}</div></div>
    <div class="when${late ? " late" : ""}">${esc(when)}</div>
    <div class="est">${esc(r.est_label || "")}</div>
    <div class="acts">${rowActions(r)}</div>
  </div>`;
}

function head(title, extra = "") {
  return `<div class="head"><h1>${esc(title)}</h1>${extra}
    <input class="search" type="search" placeholder="Search  ( / )" value="${esc(S.q)}" aria-label="Search"></div>
    ${mobileAreas()}`;
}

function mobileAreas() {
  const b = (v, label) => `<button type="button" class="btn${S.area === v ? " primary" : ""}" data-area="${v}">${label}</button>`;
  return `<div class="mobile-areas" role="group" aria-label="Area">${b("", "All")}${b("work", "Work")}${b("personal", "Personal")}</div>`;
}

// ---- Today ------------------------------------------------------------------

function renderToday() {
  const d = S.data;
  const day = parseISO(d.today);
  const sections = d.sections
    .map((s) => ({ ...s, items: s.items.filter(inArea) }))
    .filter((s) => s.items.length);
  const doing = sections.filter((s) => s.key !== "blocked").flatMap((s) => s.items);
  const blocked = sections.find((s) => s.key === "blocked")?.items.length || 0;
  const work = doing.filter((r) => r.area === "work").length;
  const personal = doing.length - work;

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
  const freeMin = S.free?.minutes ?? (Number(localStorage.getItem("hq.free")) || 30);

  const tally = [
    work ? `<div><b>${work}</b> work</div>` : "",
    personal ? `<div><b>${personal}</b> personal</div>` : "",
    blocked ? `<div><b>${blocked}</b> blocked</div>` : "",
  ].join("") || "<div>Nothing on the list</div>";

  let html = `<div class="page">
    <div class="day">
      <div class="weekday">${esc(day.toLocaleDateString(undefined, { weekday: "long" }))}</div>
      <h1 class="date">${esc(day.toLocaleDateString(undefined, { day: "numeric", month: "long" }))}</h1>
      <div class="tally">${tally}</div>
      <div class="budget">
        <div class="bar" role="img" aria-label="${fmtMinutes(total)} estimated today">${segs}${ticks}</div>
        <div class="budget-row">
          <span><span class="total">${total ? fmtMinutes(total) : "No time"}</span> estimated${noEst ? `, ${noEst} without an estimate` : ""}</span>
          <form class="free" data-form="free">
            <label for="freemin">I've got</label>
            <input id="freemin" name="minutes" type="number" min="5" step="5" value="${freeMin}">
            <span>minutes</span>
            <button class="btn" type="submit">Show what fits</button>
          </form>
        </div>
      </div>
    </div>
    ${mobileAreas()}
    <input class="search" type="search" placeholder="Search today  ( / )" value="${esc(S.q)}" aria-label="Search"${S.q ? "" : " hidden"}>`;

  if (S.free) {
    const items = S.free.items.filter(inArea).slice(0, 5);
    html += `<section class="section free-picks"><h2>Fits in ${esc(fmtMinutes(S.free.minutes))}
      <span class="count">${items.length ? "best first" : ""}</span>
      <button class="btn quiet" data-do="close-free" style="margin-left:auto">Close</button></h2>
      ${items.length ? items.map((r) => row(r, r.due ? relDue(r.due) : "")).join("")
        : `<p class="sub" style="color:var(--muted)">Nothing with an estimate fits in ${esc(fmtMinutes(S.free.minutes))}. Give entries an estimate in their details to see them here.</p>`}
    </section>`;
  }

  if (!sections.length) {
    html += `<div class="empty-state"><strong>Nothing due or planned today.</strong>
      <p>Today fills itself from due dates, do-on dates, goal deadlines and active P1/P2 work. Plan something for today, or add a task.</p>
      <button class="btn primary" data-act="new-task">New task</button>
      <a class="btn" href="/board" data-nav="board">Open the board</a></div>`;
  }
  for (const s of sections) {
    html += `<section class="section" data-section="${esc(s.key)}"><h2>${esc(s.title)}<span class="count">${s.items.length}</span></h2>
      ${s.items.map((r) => row(r, r.when)).join("")}</section>`;
  }
  return html + "</div>";
}

// ---- Board ------------------------------------------------------------------

function card(r) {
  const bits = [
    `<span class="tag-prio ${esc(r.priority)}">${esc(r.priority)}</span>`,
    `<span class="area ${esc(r.area)}">${esc(r.area)}</span>`,
    r.due && r.status !== "archive" ? `<span${daysFromToday(r.due) < 0 ? ' class="reason"' : ""}>${esc(relDue(r.due))}</span>` : "",
    r.est_label ? `<span>${esc(r.est_label)}</span>` : "",
    r.kind && r.kind !== "task" ? `<span>${esc(r.kind)}</span>` : "",
    r.blocked ? `<span class="reason">Blocked: ${esc(r.blocked)}</span>` : "",
    r.outcome === "dropped" ? "<span>dropped</span>" : "",
  ].join("");
  const cls = (r.blocked ? " blocked" : "") + (r.outcome === "dropped" ? " dropped" : "");
  return `<div class="card item${cls}" data-project="${esc(r.project)}" data-slug="${esc(r.slug)}" data-t="${esc(searchText(r))}" data-open tabindex="-1">
    <div class="title">${esc(r.title)}</div><div class="sub">${bits}</div></div>`;
}

function renderBoard() {
  const entries = S.data.entries.filter(inArea);
  const projects = [...new Set(entries.map((r) => r.project))].sort();
  let html = `<div class="page" style="max-width:1240px">${head("Board")}`;
  if (!projects.length) html += `<div class="empty-state"><strong>No entries${S.area ? ` in ${esc(S.area)}` : ""}.</strong></div>`;
  for (const p of projects) {
    const mine = entries.filter((r) => r.project === p);
    const col = (status, label) => {
      const rows = mine.filter((r) => r.status === status).sort(status === "archive"
        ? (a, b) => String(b.created).localeCompare(String(a.created)) : byPriority);
      const cards = rows.map(card).join("") || `<div class="sub" style="color:var(--muted);font-size:.85rem">Nothing here</div>`;
      const h = `${label} <span class="count">${rows.length}</span>`;
      return status === "archive"
        ? `<details class="col archive"><summary>${h}</summary>${cards}</details>`
        : `<div class="col ${status}"><h3>${h}</h3>${cards}</div>`;
    };
    html += `<section class="project"><h2>${esc(p)}</h2><div class="board">
      ${col("planning", "Planning")}${col("active", "In progress")}${col("archive", "Archive")}</div></section>`;
  }
  return html + "</div>";
}

// ---- Goals ------------------------------------------------------------------

function goalRow(g) {
  const total = g.open + g.done + g.dropped;
  const pct = (n) => (total ? (n / total) * 100 : 0);
  let target = "No target date", cls = "";
  if (g.target) {
    const n = daysFromToday(g.target);
    target = n === 0 ? "Due today" : n > 0 ? `Due in ${n} days` : `${-n} days late`;
    cls = g.status !== "active" ? "" : n < 0 ? "late" : n <= 7 ? "soon" : "";
  }
  if (g.status !== "active") target = g.status === "done" ? "Done" : "Dropped";
  const nums = total
    ? `${g.done} of ${g.open + g.done} done${g.blocked ? `, ${g.blocked} blocked` : ""}${g.dropped ? `, ${g.dropped} dropped` : ""}`
    : "No tasks yet";
  return `<div class="goal item${g.status !== "active" ? " closed" : ""}" data-goal="${esc(g.slug)}" data-t="${esc((g.title + " " + g.slug + " " + g.area).toLowerCase())}" data-open tabindex="-1">
    <span class="tag-prio ${esc(g.priority)}">${esc(g.priority)}</span>
    <div><div class="title">${esc(g.title)}</div><div class="nums"><span class="area ${esc(g.area)}">${esc(g.area)}</span> ${esc(nums)}</div></div>
    <div><div class="progress"><span class="done" style="width:${pct(g.done)}%"></span><span class="dropped" style="width:${pct(g.dropped)}%"></span></div></div>
    <div class="target ${cls}">${esc(target)}${g.target ? `<div style="font-size:.74rem">${esc(shortDate(g.target))}</div>` : ""}</div>
  </div>`;
}

function renderGoals() {
  const goals = S.data.goals.filter(inArea);
  const active = goals.filter((g) => g.status === "active").sort((a, b) =>
    prioRank(a.priority) - prioRank(b.priority) || (a.target || "9999").localeCompare(b.target || "9999"));
  const closed = goals.filter((g) => g.status !== "active");
  let html = `<div class="page">${head("Goals", `<button class="btn primary" data-act="new-goal">New goal</button>`)}`;
  if (!goals.length) {
    html += `<div class="empty-state"><strong>No goals yet.</strong>
      <p>A goal groups tasks across projects and gives them a target date. Tasks in a goal due within a week show up on Today.</p>
      <button class="btn primary" data-act="new-goal">New goal</button></div>`;
  }
  if (active.length) html += `<section class="section"><h2>Active<span class="count">${active.length}</span></h2>${active.map(goalRow).join("")}</section>`;
  if (closed.length) html += `<section class="section"><h2>Closed<span class="count">${closed.length}</span></h2>${closed.map(goalRow).join("")}</section>`;
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
  applySearch();
  select(S.sel, false);
}

function applySearch() {
  const q = S.q.trim().toLowerCase();
  $$(".item", main).forEach((el) => (el.hidden = !!q && !(el.dataset.t || "").includes(q)));
  $$(".section, .project", main).forEach((sec) => {
    if (sec.classList.contains("free-picks")) return;
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
  const act = t.closest("[data-act]");
  if (act) {
    if (act.dataset.act === "new-task") return openNewTask(act.dataset.goalDefault || "");
    if (act.dataset.act === "new-goal") return openNewGoal();
  }
  const btn = t.closest("[data-do]");
  if (btn) {
    const what = btn.dataset.do;
    if (what === "close") return closeDrawer();
    if (what === "close-free") { S.free = null; return render(); }
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
  if (kind === "free") {
    const minutes = Math.max(5, Math.round(Number(form.minutes.value) || 30));
    localStorage.setItem("hq.free", String(minutes));
    getJSON(`/api/free?minutes=${minutes}`).then((r) => { S.free = { minutes, items: r.items }; render(); })
      .catch((e) => toast(e.message, true));
    return;
  }
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
    if (S.free) { S.free = null; return render(); }
    if (S.q) { S.q = ""; return render(); }
    return;
  }
  if (typing) return;
  const keys = {
    "/": () => {
      const box = main.querySelector(".search");
      box.hidden = false;
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
