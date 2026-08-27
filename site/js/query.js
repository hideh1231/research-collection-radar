export const PAGE_SIZE = 48;
export const VIEW_STORAGE_KEY = "radar-viewer-layout";

export function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

export function parseListParam(params, key) {
  const values = params.getAll(key).flatMap((value) => value.split(",")).map((value) => value.trim()).filter(Boolean);
  return uniqueSorted(values);
}

export function parseState(search) {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const sort = params.get("sort") || "deadline";
  return {
    q: (params.get("q") || "").trim(),
    domains: parseListParam(params, "domain"),
    topics: parseListParam(params, "topic"),
    journals: parseListParam(params, "journal"),
    types: parseListParam(params, "type"),
    deadlines: parseListParam(params, "deadline"),
    sort: ["deadline", "newest", "title"].includes(sort) ? sort : "deadline",
  };
}

export function serializeState(state) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  for (const value of state.domains || []) params.append("domain", value);
  for (const value of state.topics || []) params.append("topic", value);
  for (const value of state.journals || []) params.append("journal", value);
  for (const value of state.types || []) params.append("type", value);
  for (const value of state.deadlines || []) params.append("deadline", value);
  if (state.sort && state.sort !== "deadline") params.set("sort", state.sort);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function haystack(row) {
  return [
    row.title,
    row.summary,
    row.journal,
    ...(row.journals || []),
    ...(row.domains || []),
    ...(row.topics || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function matchesQuery(row, query) {
  if (!query) return true;
  return haystack(row).includes(query.trim().toLowerCase());
}

export function matchesFacet(selected, values) {
  if (!selected || selected.length === 0) return true;
  const set = new Set((values || []).map(String));
  return selected.some((item) => set.has(item));
}

export function filterRecords(records, state) {
  return records.filter((row) => {
    if (!matchesQuery(row, state.q)) return false;
    if (!matchesFacet(state.domains, row.domains)) return false;
    if (!matchesFacet(state.topics, row.topics)) return false;
    if (!matchesFacet(state.journals, [row.journal, ...(row.journals || [])])) return false;
    if (!matchesFacet(state.types, [row.collection_type])) return false;
    if (!matchesFacet(state.deadlines, [row.deadline_status])) return false;
    return true;
  });
}

export function sortRecords(records, sort, today) {
  const copy = records.slice();
  if (sort === "title") {
    copy.sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
    return copy;
  }
  if (sort === "newest") {
    copy.sort((a, b) => String(b.first_seen || "").localeCompare(String(a.first_seen || "")) || String(a.title || "").localeCompare(String(b.title || "")));
    return copy;
  }
  copy.sort((a, b) => {
    const aDate = a.deadline || "9999-99-99";
    const bDate = b.deadline || "9999-99-99";
    if (aDate !== bDate) return aDate.localeCompare(bDate);
    return String(a.title || "").localeCompare(String(b.title || ""));
  });
  return copy;
}

export function paginate(records, visibleCount, pageSize = PAGE_SIZE) {
  const visible = Math.max(pageSize, visibleCount || pageSize);
  return {
    items: records.slice(0, visible),
    remaining: Math.max(0, records.length - visible),
    visible: Math.min(visible, records.length),
  };
}

export function daysUntil(deadline, today) {
  if (!deadline) return null;
  const start = Date.parse(`${today}T00:00:00Z`);
  const end = Date.parse(`${deadline}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.round((end - start) / 86400000);
}

export function hasActiveFilters(state) {
  return Boolean(
    state.q ||
      (state.domains && state.domains.length) ||
      (state.topics && state.topics.length) ||
      (state.journals && state.journals.length) ||
      (state.types && state.types.length) ||
      (state.deadlines && state.deadlines.length)
  );
}

export function emptyState() {
  return { q: "", domains: [], topics: [], journals: [], types: [], deadlines: [], sort: "deadline" };
}
