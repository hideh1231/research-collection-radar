import {
  PAGE_SIZE,
  TOPIC_CHIP_LIMIT,
  VIEW_STORAGE_KEY,
  countedValues,
  daysUntil,
  emptyState,
  facetCounts,
  filterRecords,
  foldTopicCasing,
  hasActiveFilters,
  paginate,
  parseState,
  recordsWithoutFacet,
  sanitizeRecord,
  serializeState,
  sortRecords,
} from "./query.js";

const TYPE_LABELS = {
  collection: "Collection",
  special_issue: "Special Issue",
  research_topic: "Research Topic",
  special_section: "Special Section",
  special_collection: "Special Collection",
  theme_issue: "Theme Issue",
  article_collection: "Article Collection",
  pacmhci_track: "PACMHCI Track",
};

const DOMAIN_LABELS = {
  psychology: "Psychology",
  hci: "HCI",
  neuroscience: "Neuroscience",
  robotics: "Robotics",
  hri: "HRI",
};

const DEADLINE_LABELS = {
  listed: "Date listed",
  not_listed: "Not listed",
  not_checked: "Not checked",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TOPIC_LIST_LIMIT = 80;
const today = new Date().toISOString().slice(0, 10);
let records = [];
let state = parseState(window.location.search);
let visibleCount = PAGE_SIZE;
let layout = window.localStorage.getItem(VIEW_STORAGE_KEY) === "table" ? "table" : "cards";
let searchTimer = 0;

function $(selector) {
  return document.querySelector(selector);
}

function escapeAttr(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!match) return iso || "";
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

function deadlineCopy(row) {
  if (row.deadline) {
    const days = daysUntil(row.deadline, today);
    const date = formatDate(row.deadline);
    if (days === null) return { modifier: "listed", label: date };
    if (days < 0) return { modifier: "past", label: `${date} · ${Math.abs(days)}d ago` };
    if (days === 0) return { modifier: "soon", label: `${date} · Today` };
    const relative = `${days}d left`;
    return { modifier: days <= 21 ? "soon" : "listed", label: `${date} · ${relative}` };
  }
  if (row.deadline_status === "not_checked") return { modifier: "unchecked", label: "Deadline not checked" };
  return { modifier: "missing", label: "Deadline not listed" };
}

function imageMarkup(row) {
  if (!row.image_url) return "";
  const alt = row.image_alt || row.title || "Collection image";
  return `<img class="cover" src="${escapeAttr(row.image_url)}" alt="${escapeAttr(alt)}" width="640" height="360" loading="lazy" referrerpolicy="no-referrer" data-fallback>`;
}

function topicChips(row) {
  const topics = row.topics || [];
  if (!topics.length) return "";
  const visible = topics.slice(0, TOPIC_CHIP_LIMIT);
  const extra = topics.slice(TOPIC_CHIP_LIMIT);
  const items = visible.map((topic) => `<li title="${escapeAttr(topic)}">${escapeHtml(topic)}</li>`);
  if (extra.length) {
    items.push(`<li class="chip-more" title="${escapeAttr(extra.join(", "))}">+${extra.length}</li>`);
  }
  return `<ul class="chips">${items.join("")}</ul>`;
}

function domainChips(row) {
  return (row.domains || []).map((domain) => DOMAIN_LABELS[domain] || domain).join(" · ");
}

function cardMarkup(row) {
  const deadline = deadlineCopy(row);
  const type = TYPE_LABELS[row.collection_type] || row.collection_type;
  const summary = row.summary
    ? `<details class="summary-details"><summary>Description</summary><p>${escapeHtml(row.summary)}</p></details>`
    : "";
  return `<article class="card card-${deadline.modifier}" data-id="${escapeAttr(row.id)}">
    ${imageMarkup(row)}
    <div class="card-body">
      <div class="card-kicker">
        <span class="deadline-badge deadline-${deadline.modifier}">${escapeHtml(deadline.label)}</span>
        <span class="type-pill">${escapeHtml(type)}</span>
      </div>
      <h2><a href="${escapeAttr(row.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.title)}</a></h2>
      <p class="journal">${escapeHtml(row.journal)}</p>
      <p class="fields">${escapeHtml(domainChips(row))}</p>
      ${summary}
      ${topicChips(row)}
    </div>
  </article>`;
}

function tableRowMarkup(row) {
  const deadline = deadlineCopy(row);
  return `<tr>
    <td><span class="deadline-badge deadline-${deadline.modifier}">${escapeHtml(deadline.label)}</span></td>
    <td class="title-cell"><a href="${escapeAttr(row.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.title)}</a></td>
    <td class="journal-cell">${escapeHtml(row.journal)}</td>
    <td>${escapeHtml(domainChips(row))}</td>
    <td>${topicChips(row)}</td>
    <td>${escapeHtml(TYPE_LABELS[row.collection_type] || row.collection_type)}</td>
  </tr>`;
}

function isAllSelected(selected) {
  return !selected || selected.length === 0;
}

function facetWithout(name) {
  return recordsWithoutFacet(records, state, name).length;
}

function journalValues(row) {
  return [...new Set([row.journal, ...(row.journals || [])].filter(Boolean))];
}

function toggleValue(list, value) {
  const next = new Set(list || []);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return [...next];
}

function chipButtons(items, selected, labels, allCount) {
  const on = new Set(selected || []);
  const allOn = on.size === 0;
  const allLabel = allCount != null ? `All (${allCount})` : "All";
  const chips = [
    `<button type="button" class="chip-toggle" data-value="__all__" aria-pressed="${allOn ? "true" : "false"}">${escapeHtml(allLabel)}</button>`,
  ];
  for (const item of items) {
    const value = item.value || item;
    const label = (labels && labels[value]) || value;
    const count = item.count != null ? ` (${item.count})` : "";
    chips.push(`<button type="button" class="chip-toggle" data-value="${escapeAttr(value)}" aria-pressed="${on.has(value) ? "true" : "false"}">${escapeHtml(label)}${count}</button>`);
  }
  return chips.join("");
}

function checkItems(items, selected, allCount) {
  const on = new Set(selected || []);
  const allOn = on.size === 0;
  const allRow = `<label class="check check-all">
      <input type="checkbox" value="__all__" ${allOn ? "checked" : ""}>
      <span class="check-label">All</span>
      <span class="check-count">${allCount != null ? allCount : ""}</span>
    </label>`;
  if (!items.length) return `${allRow}<p class="fields">No matching topics</p>`;
  const rows = items.map((item) => {
    const checked = on.has(item.value);
    const disabled = !checked && item.count === 0;
    return `<label class="check${disabled ? " is-disabled" : ""}">
      <input type="checkbox" value="${escapeAttr(item.value)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
      <span class="check-label" title="${escapeAttr(item.value)}">${escapeHtml(item.value)}</span>
      <span class="check-count">${item.count}</span>
    </label>`;
  });
  return `${allRow}${rows.join("")}`;
}

function visibleList(all, selected, query, limit) {
  const selectedSet = new Set(selected || []);
  const needle = (query || "").trim().toLowerCase();
  const matching = needle
    ? all.filter((item) => item.value.toLowerCase().includes(needle) || selectedSet.has(item.value))
    : all;
  const picked = [];
  const seen = new Set();
  for (const item of matching) {
    if (selectedSet.has(item.value) && !seen.has(item.value)) {
      picked.push(item);
      seen.add(item.value);
    }
  }
  for (const item of matching) {
    if (limit != null && picked.length >= limit) break;
    if (seen.has(item.value)) continue;
    picked.push(item);
    seen.add(item.value);
  }
  return picked;
}

function activeFilterChips() {
  const chips = [];
  const push = (facet, value, label) => {
    chips.push(`<span class="active-chip">${escapeHtml(label)} <button type="button" data-facet="${escapeAttr(facet)}" data-value="${escapeAttr(value)}" aria-label="Remove ${escapeAttr(label)}">×</button></span>`);
  };
  if (state.q) push("q", state.q, `Search: ${state.q}`);
  for (const value of state.domains) push("domains", value, DOMAIN_LABELS[value] || value);
  for (const value of state.types) push("types", value, TYPE_LABELS[value] || value);
  for (const value of state.deadlines) push("deadlines", value, DEADLINE_LABELS[value] || value);
  if (state.from) push("from", state.from, `From ${state.from}`);
  if (state.to) push("to", state.to, `To ${state.to}`);
  for (const value of state.journals) push("journals", value, value);
  for (const value of state.topics) push("topics", value, value);
  return chips.join("");
}

function renderFacets() {
  const domainCounts = facetCounts(records, state, "domains", (row) => row.domains || []);
  const typeCounts = facetCounts(records, state, "types", (row) => [row.collection_type]);
  const deadlineCounts = facetCounts(records, state, "deadlines", (row) => [row.deadline_status]);
  const journalCounts = facetCounts(records, state, "journals", journalValues);
  const topicCounts = facetCounts(records, state, "topics", (row) => row.topics || []);
  const allJournals = countedValues(records, journalValues);
  const allTopics = countedValues(records, (row) => row.topics || []);
  const journalByValue = new Map(journalCounts.map((item) => [item.value, item.count]));
  const topicByValue = new Map(topicCounts.map((item) => [item.value, item.count]));

  $("#domain-filter").innerHTML = chipButtons(
    ["psychology", "hci", "neuroscience", "robotics", "hri"].map((value) => ({
      value,
      count: domainCounts.find((item) => item.value === value)?.count || 0,
    })),
    state.domains,
    DOMAIN_LABELS,
    facetWithout("domains"),
  );
  $("#type-filter").innerHTML = chipButtons(typeCounts, state.types, TYPE_LABELS, facetWithout("types"));
  $("#deadline-filter").innerHTML = chipButtons(
    ["listed", "not_listed", "not_checked"].map((value) => ({
      value,
      count: deadlineCounts.find((item) => item.value === value)?.count || 0,
    })),
    state.deadlines,
    DEADLINE_LABELS,
    facetWithout("deadlines"),
  );
  const journals = visibleList(
    allJournals.map((item) => ({ value: item.value, count: journalByValue.get(item.value) || 0 })),
    state.journals,
    $("#journal-query").value,
  );
  const topics = visibleList(
    allTopics.map((item) => ({ value: item.value, count: topicByValue.get(item.value) || 0 })),
    state.topics,
    $("#topic-query").value,
    TOPIC_LIST_LIMIT,
  );
  $("#journal-filter").innerHTML = checkItems(journals, state.journals, facetWithout("journals"));
  $("#topic-filter").innerHTML = checkItems(topics, state.topics, facetWithout("topics"));
  $("#search").value = state.q;
  $("#sort").value = state.sort;
  $("#deadline-from").value = state.from || "";
  $("#deadline-to").value = state.to || "";
}

function render() {
  const filtered = sortRecords(filterRecords(records, state), state.sort, today);
  const page = paginate(filtered, visibleCount);
  const results = $("#results");
  const empty = $("#empty");
  const count = $("#count");
  const more = $("#more");
  const clear = $("#clear");
  const active = $("#active-filters");
  count.textContent = `${filtered.length} open call${filtered.length === 1 ? "" : "s"}`;
  clear.hidden = !hasActiveFilters(state);
  more.hidden = page.remaining === 0;
  more.textContent = page.remaining ? `Show ${Math.min(PAGE_SIZE, page.remaining)} more` : "";
  $("#layout-cards").setAttribute("aria-pressed", layout === "cards" ? "true" : "false");
  $("#layout-table").setAttribute("aria-pressed", layout === "table" ? "true" : "false");
  active.hidden = !hasActiveFilters(state);
  active.innerHTML = activeFilterChips();
  renderFacets();
  if (page.items.length === 0) {
    results.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  if (layout === "table") {
    results.innerHTML = `<div class="table-wrap" tabindex="0" aria-label="Open calls">
      <table>
        <colgroup>
          <col class="deadline">
          <col class="title">
          <col class="journal">
          <col class="fields">
          <col class="topics">
          <col class="type">
        </colgroup>
        <thead><tr><th>Deadline</th><th>Title</th><th>Journal</th><th>Fields</th><th>Topics</th><th>Type</th></tr></thead>
        <tbody>${page.items.map(tableRowMarkup).join("")}</tbody>
      </table>
    </div>`;
  } else {
    results.innerHTML = `<div class="card-grid">${page.items.map(cardMarkup).join("")}</div>`;
  }
}

function syncUrl() {
  const next = serializeState(state);
  const url = `${window.location.pathname}${next}${window.location.hash}`;
  window.history.replaceState(state, "", url);
}

function applyState() {
  visibleCount = PAGE_SIZE;
  syncUrl();
  render();
}

function selectFacet(name, value) {
  if (value === "__all__") {
    if (isAllSelected(state[name])) return false;
    state = { ...state, [name]: [] };
    return true;
  }
  state = { ...state, [name]: toggleValue(state[name], value) };
  return true;
}

function bind() {
  $("#search").addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state = { ...state, q: $("#search").value.trim() };
      applyState();
    }, 150);
  });
  $("#sort").addEventListener("change", () => {
    state = { ...state, sort: $("#sort").value };
    applyState();
  });
  $("#deadline-from").addEventListener("change", () => {
    state = { ...state, from: $("#deadline-from").value };
    applyState();
  });
  $("#deadline-to").addEventListener("change", () => {
    state = { ...state, to: $("#deadline-to").value };
    applyState();
  });
  $("#journal-query").addEventListener("input", () => renderFacets());
  $("#topic-query").addEventListener("input", () => renderFacets());
  $("#domain-filter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    if (selectFacet("domains", button.dataset.value)) applyState();
  });
  $("#type-filter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    if (selectFacet("types", button.dataset.value)) applyState();
  });
  $("#deadline-filter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    if (selectFacet("deadlines", button.dataset.value)) applyState();
  });
  $("#journal-filter").addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    if (selectFacet("journals", input.value)) applyState();
    else applyState();
  });
  $("#topic-filter").addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    if (selectFacet("topics", input.value)) applyState();
    else applyState();
  });
  $("#active-filters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-facet]");
    if (!button) return;
    const facet = button.dataset.facet;
    const value = button.dataset.value;
    if (facet === "q") state = { ...state, q: "" };
    else if (facet === "from") state = { ...state, from: "" };
    else if (facet === "to") state = { ...state, to: "" };
    else state = { ...state, [facet]: (state[facet] || []).filter((item) => item !== value) };
    applyState();
  });
  $("#clear").addEventListener("click", () => {
    state = emptyState();
    $("#journal-query").value = "";
    $("#topic-query").value = "";
    applyState();
    $("#search").focus();
  });
  $("#more").addEventListener("click", () => {
    visibleCount += PAGE_SIZE;
    render();
  });
  $("#layout-cards").addEventListener("click", () => {
    layout = "cards";
    window.localStorage.setItem(VIEW_STORAGE_KEY, "cards");
    render();
  });
  $("#layout-table").addEventListener("click", () => {
    layout = "table";
    window.localStorage.setItem(VIEW_STORAGE_KEY, "table");
    render();
  });
  $("#results").addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.hasAttribute("data-fallback")) return;
    image.remove();
  }, true);
  window.addEventListener("keydown", (event) => {
    const typing = event.target instanceof HTMLInputElement
      || event.target instanceof HTMLTextAreaElement
      || event.target instanceof HTMLSelectElement
      || (event.target instanceof HTMLElement && event.target.isContentEditable);
    if (event.key === "/" && !typing) {
      event.preventDefault();
      $("#search").focus();
    }
  });
}

async function start() {
  bind();
  try {
    const response = await fetch("data/collections.json");
    if (!response.ok) throw new Error("Could not load collections");
    const payload = await response.json();
    records = Array.isArray(payload) ? foldTopicCasing(payload.map(sanitizeRecord).filter((row) => !row.status || row.status === "open")) : [];
  } catch (error) {
    $("#empty").hidden = false;
    $("#empty").textContent = "The collection index could not be loaded.";
    console.error(error);
    return;
  }
  render();
}

start();
