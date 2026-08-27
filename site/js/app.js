import {
  PAGE_SIZE,
  VIEW_STORAGE_KEY,
  daysUntil,
  emptyState,
  filterRecords,
  hasActiveFilters,
  paginate,
  parseState,
  serializeState,
  sortRecords,
  uniqueSorted,
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

const root = document.documentElement;
const today = new Date().toISOString().slice(0, 10);
let records = [];
let state = parseState(window.location.search);
let visibleCount = PAGE_SIZE;
let layout = window.localStorage.getItem(VIEW_STORAGE_KEY) === "table" ? "table" : "cards";

function $(selector) {
  return document.querySelector(selector);
}

function optionList(values, labels) {
  return uniqueSorted(values).map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = (labels && labels[value]) || value;
    return option;
  });
}

function fillSelect(select, values, selected, labels) {
  const current = new Set(selected);
  select.innerHTML = "";
  for (const option of optionList(values, labels)) {
    option.selected = current.has(option.value);
    select.append(option);
  }
}

function selectedValues(select) {
  return [...select.selectedOptions].map((option) => option.value);
}

function deadlineCopy(row) {
  if (row.deadline) {
    const days = daysUntil(row.deadline, today);
    if (days === null) return { label: row.deadline, modifier: "listed" };
    if (days < 0) return { label: `${Math.abs(days)}d ago`, modifier: "past" };
    if (days === 0) return { label: "Today", modifier: "soon" };
    if (days <= 21) return { label: `${days}d`, modifier: "soon" };
    return { label: `${days}d`, modifier: "listed" };
  }
  if (row.deadline_status === "not_checked") return { label: "Not checked", modifier: "unchecked" };
  return { label: "Not listed", modifier: "missing" };
}

function imageMarkup(row) {
  if (!row.image_url) {
    return `<div class="thumb thumb-empty" aria-hidden="true"></div>`;
  }
  const alt = row.image_alt || row.title || "Collection image";
  return `<img class="thumb" src="${escapeAttr(row.image_url)}" alt="${escapeAttr(alt)}" loading="lazy" referrerpolicy="no-referrer" data-fallback>`;
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

function topicChips(row) {
  const topics = row.topics || [];
  if (!topics.length) return "";
  return `<ul class="chips">${topics.map((topic) => `<li>${escapeHtml(topic)}</li>`).join("")}</ul>`;
}

function domainChips(row) {
  return (row.domains || []).map((domain) => DOMAIN_LABELS[domain] || domain).join(" · ");
}

function cardMarkup(row) {
  const rail = deadlineCopy(row);
  const summary = row.summary ? escapeHtml(row.summary) : "No summary listed.";
  return `<article class="card" data-id="${escapeAttr(row.id)}">
    <div class="rail rail-${rail.modifier}" aria-label="Deadline ${escapeAttr(rail.label)}">
      <span>${escapeHtml(rail.label)}</span>
    </div>
    <div class="card-body">
      ${imageMarkup(row)}
      <div class="card-copy">
        <p class="meta">${escapeHtml(domainChips(row))} · ${escapeHtml(TYPE_LABELS[row.collection_type] || row.collection_type)}</p>
        <h2><a href="${escapeAttr(row.url)}" rel="noopener noreferrer">${escapeHtml(row.title)}</a></h2>
        <p class="journal">${escapeHtml(row.journal)}</p>
        <p class="summary" data-expanded="false">${summary}</p>
        ${row.summary && row.summary.length > 180 ? `<button type="button" class="text-toggle">Expand summary</button>` : ""}
        ${topicChips(row)}
      </div>
    </div>
  </article>`;
}

function tableRowMarkup(row) {
  const rail = deadlineCopy(row);
  return `<tr>
    <td><span class="rail-inline rail-${rail.modifier}">${escapeHtml(rail.label)}</span></td>
    <td><a href="${escapeAttr(row.url)}" rel="noopener noreferrer">${escapeHtml(row.title)}</a></td>
    <td>${escapeHtml(row.journal)}</td>
    <td>${escapeHtml(domainChips(row))}</td>
    <td>${escapeHtml((row.topics || []).join(", "))}</td>
    <td>${escapeHtml(TYPE_LABELS[row.collection_type] || row.collection_type)}</td>
  </tr>`;
}

function renderFacets(filtered) {
  fillSelect($("#domain-filter"), records.flatMap((row) => row.domains || []), state.domains, DOMAIN_LABELS);
  fillSelect($("#topic-filter"), records.flatMap((row) => row.topics || []), state.topics);
  fillSelect($("#journal-filter"), records.map((row) => row.journal), state.journals);
  fillSelect($("#type-filter"), records.map((row) => row.collection_type), state.types, TYPE_LABELS);
  fillSelect($("#deadline-filter"), ["listed", "not_listed", "not_checked"], state.deadlines, DEADLINE_LABELS);
  $("#search").value = state.q;
  $("#sort").value = state.sort;
  void filtered;
}

function render() {
  const filtered = sortRecords(filterRecords(records, state), state.sort, today);
  const page = paginate(filtered, visibleCount);
  const results = $("#results");
  const empty = $("#empty");
  const count = $("#count");
  const more = $("#more");
  const clear = $("#clear");
  count.textContent = `${filtered.length} open call${filtered.length === 1 ? "" : "s"}`;
  clear.hidden = !hasActiveFilters(state);
  more.hidden = page.remaining === 0;
  more.textContent = page.remaining ? `Show ${Math.min(PAGE_SIZE, page.remaining)} more` : "";
  $("#layout-cards").setAttribute("aria-pressed", layout === "cards" ? "true" : "false");
  $("#layout-table").setAttribute("aria-pressed", layout === "table" ? "true" : "false");
  document.body.dataset.layout = layout;
  if (page.items.length === 0) {
    results.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  if (layout === "table") {
    results.innerHTML = `<div class="table-wrap" tabindex="0"><table>
      <thead><tr><th>Deadline</th><th>Title</th><th>Journal</th><th>Fields</th><th>Topics</th><th>Type</th></tr></thead>
      <tbody>${page.items.map(tableRowMarkup).join("")}</tbody>
    </table></div>`;
  } else {
    results.innerHTML = `<div class="card-grid">${page.items.map(cardMarkup).join("")}</div>`;
  }
}

function syncUrl() {
  const next = serializeState(state);
  const url = `${window.location.pathname}${next}${window.location.hash}`;
  window.history.replaceState(state, "", url);
}

function readControls() {
  state = {
    q: $("#search").value.trim(),
    domains: selectedValues($("#domain-filter")),
    topics: selectedValues($("#topic-filter")),
    journals: selectedValues($("#journal-filter")),
    types: selectedValues($("#type-filter")),
    deadlines: selectedValues($("#deadline-filter")),
    sort: $("#sort").value,
  };
  visibleCount = PAGE_SIZE;
  syncUrl();
  render();
}

function bind() {
  $("#search").addEventListener("input", readControls);
  for (const id of ["domain-filter", "topic-filter", "journal-filter", "type-filter", "deadline-filter", "sort"]) {
    $(`#${id}`).addEventListener("change", readControls);
  }
  $("#clear").addEventListener("click", () => {
    state = emptyState();
    visibleCount = PAGE_SIZE;
    renderFacets(records);
    syncUrl();
    render();
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
  $("#results").addEventListener("click", (event) => {
    const button = event.target.closest(".text-toggle");
    if (!button) return;
    const summary = button.parentElement.querySelector(".summary");
    const expanded = summary.getAttribute("data-expanded") === "true";
    summary.setAttribute("data-expanded", expanded ? "false" : "true");
    button.textContent = expanded ? "Expand summary" : "Collapse summary";
  });
  $("#results").addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.hasAttribute("data-fallback")) return;
    const placeholder = document.createElement("div");
    placeholder.className = "thumb thumb-empty";
    placeholder.setAttribute("aria-hidden", "true");
    image.replaceWith(placeholder);
  }, true);
  window.addEventListener("keydown", (event) => {
    if (event.key === "/" && event.target === document.body) {
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
    records = await response.json();
    if (!Array.isArray(records) || records.some((row) => row.status && row.status !== "open")) {
      records = Array.isArray(records) ? records.filter((row) => row.status === "open") : [];
    }
  } catch (error) {
    $("#empty").hidden = false;
    $("#empty").textContent = "The collection index could not be loaded.";
    console.error(error);
    return;
  }
  renderFacets(records);
  render();
}

start();
void root;
