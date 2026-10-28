const state = {
  wars: [],
  ignitions: [],
  connected: false,
  caughtUp: false,
  uiDown: false,
  lastError: "",
  lastEventAt: null,
  generatedAt: null,
  ingested: 0,
  reverts: 0,
  rate: 0,
  total: 0,
  articles: 0,
  windowHours: 6,
  wikis: [],
  wiki: "",
  selected: "",
  detail: null,
};

let source = null;
let downTimer = 0;
let detailStamp = "";

const boardEl = document.getElementById("board");
const feedEl = document.getElementById("feed");
const detailEl = document.getElementById("detail");
const bannerEl = document.getElementById("banner");
const metersEl = document.getElementById("meters");
const filtersEl = document.getElementById("filters");
const windowEl = document.getElementById("window-hours");

function h(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value == null || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, String(value));
  });
  (children || []).forEach((child) => {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}

function rel(iso) {
  if (!iso) return "";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(seconds)) return "";
  if (seconds < 15) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  if (hours < 36) return rem ? `${hours}h ${rem}m ago` : `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function clock(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function stamp(iso) {
  return h("time", { datetime: iso, "data-time": iso }, [rel(iso)]);
}

function compact(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1).replace(/\.0$/, "")}k`;
  return String(value);
}

function keyOf(wiki, title) {
  return `${wiki}\n${title}`;
}

function warUrl(wiki, title) {
  const path = title.split("/").map(encodeURIComponent).join("/");
  return `/wars/${encodeURIComponent(wiki)}/${path}`;
}

async function loadBoard() {
  const query = new URLSearchParams({ limit: "50" });
  if (state.wiki) query.set("wiki", state.wiki);
  const response = await fetch(`/wars?${query}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  applySnapshot(await response.json());
}

function applySnapshot(data) {
  state.wars = data.wars || [];
  state.ignitions = data.ignitions || [];
  state.connected = Boolean(data.stream_connected);
  state.caughtUp = Boolean(data.caught_up);
  state.lastError = data.last_error || "";
  state.lastEventAt = data.last_event_at || null;
  state.generatedAt = data.generated_at || null;
  state.ingested = data.ingested_edits || 0;
  state.reverts = data.reverts_seen || 0;
  state.rate = data.edits_per_minute || 0;
  state.total = data.total || 0;
  state.articles = data.articles || 0;
  state.windowHours = data.window_hours || 6;
  state.wikis = data.wikis || [];
  if (windowEl) windowEl.textContent = String(state.windowHours);
  document.title = state.total ? `(${state.total}) Edit-War Radar` : "Edit-War Radar";
  render();
  if (state.selected) refreshDetail();
}

function applyStatus(data) {
  state.connected = Boolean(data.stream_connected);
  state.caughtUp = Boolean(data.caught_up);
  state.lastError = data.last_error || "";
  state.lastEventAt = data.last_event_at || null;
  state.generatedAt = data.generated_at || null;
  state.ingested = data.ingested_edits || 0;
  state.reverts = data.reverts_seen || 0;
  state.rate = data.edits_per_minute || 0;
  if (typeof data.total === "number") state.total = data.total;
  renderChrome();
}

function pushIgnition(item) {
  if (state.ignitions.some((existing) => existing.id === item.id)) return;
  state.ignitions = [item, ...state.ignitions].slice(0, 40);
  renderFeed();
}

function connectStream() {
  if (source) source.close();
  source = new EventSource("/stream");
  source.addEventListener("hello", (event) => applySnapshot(JSON.parse(event.data)));
  source.addEventListener("leaderboard", (event) => {
    const data = JSON.parse(event.data);
    if (state.wiki) loadBoard().catch(showLoadError);
    else applySnapshot(data);
  });
  source.addEventListener("status", (event) => applyStatus(JSON.parse(event.data)));
  source.addEventListener("ignition", (event) => {
    pushIgnition(JSON.parse(event.data));
    loadBoard().catch(showLoadError);
  });
  source.onopen = () => {
    window.clearTimeout(downTimer);
    state.uiDown = false;
    renderChrome();
  };
  source.onerror = () => {
    window.clearTimeout(downTimer);
    downTimer = window.setTimeout(() => {
      state.uiDown = true;
      renderChrome();
    }, 2000);
  };
}

function showLoadError(error) {
  bannerEl.hidden = false;
  bannerEl.className = "banner bad";
  bannerEl.textContent = `Can't reach the radar API (${error.message}).`;
}

function render() {
  renderChrome();
  renderFilters();
  renderBoard();
  renderFeed();
}

function renderChrome() {
  const mode = state.uiDown ? "down" : state.connected ? "live" : "wait";
  const label = state.uiDown ? "Dashboard link down" : state.connected ? (state.caughtUp ? "Live" : "Replaying") : "Stream down";
  metersEl.replaceChildren(
    h("div", { class: `pulse ${mode}` }, [h("i"), label]),
    h("div", { class: "rate" }, [`${state.rate} edits/min · ${state.reverts} reverts kept`]),
    h("div", { class: "updated" }, state.generatedAt ? [stamp(state.generatedAt)] : ["waiting"]),
  );
  if (state.uiDown) {
    bannerEl.hidden = false;
    bannerEl.className = "banner bad";
    bannerEl.textContent = "Dashboard disconnected from the API. Retrying. The table stays on the last update.";
    return;
  }
  if (!state.connected) {
    bannerEl.hidden = false;
    bannerEl.className = "banner";
    bannerEl.textContent = state.lastError
      ? `Wikipedia stream disconnected (${state.lastError}). Showing the last window we have.`
      : "Wikipedia stream disconnected. Showing the last window we have.";
    return;
  }
  if (!state.caughtUp) {
    bannerEl.hidden = false;
    bannerEl.className = "banner";
    bannerEl.textContent = "Replaying recent edits into the window. Wars appear as the backlog catches up.";
    return;
  }
  bannerEl.hidden = true;
  bannerEl.textContent = "";
}

function renderFilters() {
  if (state.wikis.length < 2) {
    filtersEl.replaceChildren();
    return;
  }
  const buttons = [filterButton("", "All")].concat(state.wikis.map((wiki) => filterButton(wiki, wiki.replace(".wikipedia.org", ""))));
  filtersEl.replaceChildren(...buttons);
}

function filterButton(wiki, label) {
  return h("button", {
    type: "button",
    "aria-pressed": state.wiki === wiki ? "true" : "false",
    onclick: () => {
      state.wiki = wiki;
      loadBoard().catch(showLoadError);
    },
  }, [label]);
}

function renderBoard() {
  if (!state.wars.length) {
    const listening = state.connected
      ? "Listening. English Wikipedia usually puts at least one article over two reverts within an hour."
      : "No war is in the current window yet.";
    boardEl.replaceChildren(h("p", { class: "empty" }, [listening]));
    return;
  }
  const maxScore = Math.max(...state.wars.map((war) => war.score), 1);
  boardEl.replaceChildren(...state.wars.map((war, index) => warCard(war, index, maxScore)));
}

function warCard(war, index, maxScore) {
  const selected = state.selected === keyOf(war.wiki, war.title);
  const classes = ["war", war.mutual_war ? "mutual" : "", index === 0 ? "lead" : "", selected ? "selected" : ""].filter(Boolean).join(" ");
  const width = Math.max(8, Math.round((war.score / maxScore) * 100));
  const bar = h("div", { class: "bar", title: `score ${war.score}` }, [h("span", { style: `width:${width}%` })]);
  const title = h("h3", { class: "title" }, [war.title]);
  const people = war.reverters.slice(0, 4).join(", ");
  const extra = war.reverters.length > 4 ? ` +${war.reverters.length - 4}` : "";
  const meta = [
    `${war.reverts} reverts`,
    `${war.distinct_reverters} editors`,
    `${war.edits} edits`,
  ];
  if (war.mutual_war) meta.push("mutual");
  const card = h("article", { class: classes }, [
    h("div", { class: "war-top" }, [
      h("span", { class: "rank" }, [String(index + 1).padStart(2, "0")]),
      h("span", { class: "score" }, [String(war.score)]),
      bar,
    ]),
    title,
    h("div", { class: "meta" }, [
      ...meta.map((item) => h("span", {}, [item])),
      war.war_started_at ? stamp(war.war_started_at) : "",
      war.views == null ? "" : h("span", {}, [`${compact(war.views)} views`]),
      war.url ? h("a", { class: "wiki", href: war.url, target: "_blank", rel: "noopener noreferrer" }, ["wiki"]) : "",
    ]),
    people ? h("div", { class: "people" }, [`${people}${extra}`]) : h("div"),
  ]);
  card.tabIndex = 0;
  card.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    select(war);
  });
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(war);
    }
  });
  return card;
}

function renderFeed() {
  if (!state.ignitions.length) {
    feedEl.replaceChildren(h("p", { class: "empty" }, ["No ignition yet. An article joins this feed when a second revert lands."]));
    return;
  }
  feedEl.replaceChildren(...state.ignitions.map((item) => {
    const kind = item.kind === "mutual" ? "Mutual" : "War ignited";
    const button = h("button", { type: "button", onclick: () => select(item) }, [item.title]);
    return h("article", { class: "ignition" }, [
      h("div", { class: "kind" }, [kind]),
      button,
      h("div", { class: "when" }, [clock(item.at), " · ", `${item.reverts} reverts`]),
    ]);
  }));
}

function select(war) {
  state.selected = keyOf(war.wiki, war.title);
  detailStamp = "";
  renderBoard();
  refreshDetail(true);
}

async function refreshDetail(scroll) {
  if (!state.selected) return;
  const [wiki, title] = state.selected.split("\n");
  const response = await fetch(warUrl(wiki, title));
  if (response.status === 404) {
    detailEl.hidden = false;
    detailEl.replaceChildren(h("p", { class: "empty" }, ["That article has fallen out of the window."]));
    return;
  }
  if (!response.ok) return;
  const data = await response.json();
  const stampValue = `${data.score}|${data.reverts}|${(data.timeline || []).length}`;
  if (stampValue === detailStamp) return;
  detailStamp = stampValue;
  state.detail = data;
  renderDetail(data);
  if (scroll && window.innerWidth < 860) detailEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDetail(data) {
  detailEl.hidden = false;
  const mutual = (data.mutual || []).map((pair) => `${pair.a} ⇄ ${pair.b}`).join(", ");
  const people = (data.participants || []).map((person) => h("span", {}, [
    `${person.name} · ${person.reverts_made} sent / ${person.times_reverted} received`,
  ]));
  const timeline = (data.timeline || []).map((item) => h("article", { class: "revert" }, [
    h("div", { class: "who" }, [
      stamp(item.timestamp),
      " ",
      h("b", {}, [item.user]),
      item.reverted_user ? ` reverted ${item.reverted_user}` : " reverted",
    ]),
    h("blockquote", {}, [item.comment || "(no comment)"]),
  ]));
  const children = [
    h("h3", {}, [data.title]),
    h("div", { class: "meta" }, [
      h("span", { class: "score" }, [String(data.score)]),
      `${data.reverts} reverts`,
      data.mutual_war ? h("span", { class: "pill" }, ["Mutual"]) : "",
      data.url ? h("a", { class: "wiki", href: data.url, target: "_blank", rel: "noopener noreferrer" }, ["Open article"]) : "",
    ]),
  ];
  if (mutual) children.push(h("p", { class: "people" }, [mutual]));
  if ((data.score_history || []).length > 1) children.push(sparkline(data.score_history));
  if (people.length) children.push(h("div", { class: "people" }, people));
  children.push(h("div", { class: "timeline" }, timeline.length ? timeline : [h("p", { class: "empty" }, ["No reverts left in the window."])]));
  detailEl.replaceChildren(...children);
}

function sparkline(points) {
  const width = 280;
  const height = 64;
  const pad = 4;
  const scores = points.map((point) => point.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const span = Math.max(1, max - min);
  const step = points.length === 1 ? 0 : (width - pad * 2) / (points.length - 1);
  const coords = points.map((point, index) => {
    const x = pad + index * step;
    const y = pad + (1 - (point.score - min) / span) * (height - pad * 2);
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Score over the last hour of samples");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", coords);
  svg.append(path);
  return svg;
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.selected) {
    state.selected = "";
    detailStamp = "";
    detailEl.hidden = true;
    detailEl.replaceChildren();
    renderBoard();
  }
});

window.setInterval(() => {
  document.querySelectorAll("[data-time]").forEach((node) => {
    node.textContent = rel(node.getAttribute("data-time"));
  });
}, 15000);

loadBoard().catch(showLoadError);
connectStream();
