import assert from "node:assert/strict";
import test from "node:test";

import {
  PAGE_SIZE,
  emptyState,
  facetCounts,
  filterRecords,
  hasActiveFilters,
  paginate,
  parseState,
  sanitizeTopics,
  serializeState,
  sortRecords,
  splitKeywordText,
} from "../../site/js/query.js";

function row(id, updates = {}) {
  return {
    id,
    title: updates.title || `Title ${id}`,
    summary: updates.summary || `Summary about ${id}`,
    journal: updates.journal || "Frontiers in Psychology",
    journals: updates.journals || [updates.journal || "Frontiers in Psychology"],
    domains: updates.domains || ["psychology"],
    topics: updates.topics || ["aging"],
    collection_type: updates.collection_type || "research_topic",
    deadline: updates.deadline === undefined ? "2027-01-02" : updates.deadline,
    deadline_status: updates.deadline_status || (updates.deadline === null ? "not_listed" : "listed"),
    first_seen: updates.first_seen || "2026-08-01",
    status: "open",
  };
}

const catalog = [
  row("a", { title: "Aging and AI", summary: "Wearables and well-being", topics: ["AI", "aging"], deadline: "2027-02-01" }),
  row("b", { title: "Robot tutoring", journal: "Frontiers in Robotics and AI", domains: ["robotics", "hri"], topics: ["HRI"], deadline: "2026-09-01", collection_type: "collection" }),
  row("c", { title: "Sleep studies", summary: "Circadian work", domains: ["neuroscience"], topics: ["sleep"], deadline: null, deadline_status: "not_listed", first_seen: "2026-08-26" }),
  row("d", { title: "Later collection", deadline: "2028-01-01", first_seen: "2026-07-01", topics: ["AI"] }),
];

test("full-text search covers title summary journal domains and topics", () => {
  const byTitle = filterRecords(catalog, { ...emptyState(), q: "robot tutoring" });
  const bySummary = filterRecords(catalog, { ...emptyState(), q: "wearables" });
  const byJournal = filterRecords(catalog, { ...emptyState(), q: "robotics and ai" });
  const byDomain = filterRecords(catalog, { ...emptyState(), q: "hri" });
  const byTopic = filterRecords(catalog, { ...emptyState(), q: "sleep" });
  assert.deepEqual(byTitle.map((item) => item.id), ["b"]);
  assert.deepEqual(bySummary.map((item) => item.id), ["a"]);
  assert.deepEqual(byJournal.map((item) => item.id), ["b"]);
  assert.deepEqual(byDomain.map((item) => item.id), ["b"]);
  assert.deepEqual(byTopic.map((item) => item.id), ["c"]);
});

test("multiple filters combine across facets", () => {
  const filtered = filterRecords(catalog, {
    ...emptyState(),
    domains: ["psychology"],
    topics: ["AI"],
    journals: ["Frontiers in Psychology"],
    types: ["research_topic"],
    deadlines: ["listed"],
  });
  assert.deepEqual(filtered.map((item) => item.id).sort(), ["a", "d"]);
});

test("multiple values in one facet match as OR", () => {
  const journals = filterRecords(catalog, {
    ...emptyState(),
    journals: ["Frontiers in Psychology", "Frontiers in Robotics and AI"],
  });
  assert.deepEqual(journals.map((item) => item.id).sort(), ["a", "b", "c", "d"]);
  const onlyRobotics = filterRecords(catalog, {
    ...emptyState(),
    journals: ["Frontiers in Robotics and AI"],
  });
  assert.deepEqual(onlyRobotics.map((item) => item.id), ["b"]);
  const topics = filterRecords(catalog, {
    ...emptyState(),
    topics: ["HRI", "sleep"],
  });
  assert.deepEqual(topics.map((item) => item.id).sort(), ["b", "c"]);
});

test("facetCounts ignore the selected values of that facet", () => {
  const journalValues = (row) => [...new Set([row.journal, ...(row.journals || [])])];
  const counts = facetCounts(
    catalog,
    { ...emptyState(), journals: ["Frontiers in Psychology"] },
    "journals",
    journalValues,
  );
  const byValue = Object.fromEntries(counts.map((item) => [item.value, item.count]));
  assert.equal(byValue["Frontiers in Psychology"], 3);
  assert.equal(byValue["Frontiers in Robotics and AI"], 1);
});

test("facetCounts still respect other facets", () => {
  const counts = facetCounts(
    catalog,
    { ...emptyState(), domains: ["robotics"], journals: ["Frontiers in Robotics and AI"] },
    "journals",
    (row) => [...new Set([row.journal, ...(row.journals || [])])],
  );
  const byValue = Object.fromEntries(counts.map((item) => [item.value, item.count]));
  assert.equal(byValue["Frontiers in Robotics and AI"], 1);
  assert.equal(byValue["Frontiers in Psychology"], undefined);
});

test("sorts by deadline, newest, and title", () => {
  const byDeadline = sortRecords(catalog, "deadline").map((item) => item.id);
  const byNewest = sortRecords(catalog, "newest").map((item) => item.id);
  const byTitle = sortRecords(catalog, "title").map((item) => item.id);
  assert.deepEqual(byDeadline, ["b", "a", "d", "c"]);
  assert.equal(byNewest[0], "c");
  assert.deepEqual(byTitle, ["Aging and AI", "Later collection", "Robot tutoring", "Sleep studies"].map((title) => catalog.find((item) => item.title === title).id));
});

test("url state round-trips search and filters", () => {
  const original = {
    q: "aging",
    domains: ["hci", "psychology"],
    topics: ["AI"],
    journals: ["Frontiers in Psychology"],
    types: ["research_topic"],
    deadlines: ["listed"],
    from: "2027-01-01",
    to: "2027-12-31",
    sort: "title",
  };
  const encoded = serializeState(original);
  const restored = parseState(encoded);
  assert.equal(restored.q, "aging");
  assert.deepEqual(restored.domains, ["hci", "psychology"]);
  assert.deepEqual(restored.topics, ["AI"]);
  assert.deepEqual(restored.journals, ["Frontiers in Psychology"]);
  assert.deepEqual(restored.types, ["research_topic"]);
  assert.deepEqual(restored.deadlines, ["listed"]);
  assert.equal(restored.from, "2027-01-01");
  assert.equal(restored.to, "2027-12-31");
  assert.equal(restored.sort, "title");
  assert.equal(hasActiveFilters(restored), true);
});

test("deadline date range keeps dated rows and optional undated statuses", () => {
  const ranged = filterRecords(catalog, { ...emptyState(), from: "2027-01-01", to: "2027-12-31" });
  assert.deepEqual(ranged.map((item) => item.id), ["a"]);
  const withUndated = filterRecords(catalog, {
    ...emptyState(),
    from: "2026-01-01",
    to: "2026-12-31",
    deadlines: ["not_listed"],
  });
  assert.deepEqual(withUndated.map((item) => item.id).sort(), ["b", "c"]);
});

test("loads 48 more records at a time", () => {
  const many = Array.from({ length: 100 }, (_, index) => row(String(index)));
  const first = paginate(many, PAGE_SIZE);
  assert.equal(first.items.length, 48);
  assert.equal(first.remaining, 52);
  const second = paginate(many, PAGE_SIZE * 2);
  assert.equal(second.items.length, 96);
  assert.equal(second.remaining, 4);
});

test("empty facet selection means all records", () => {
  const filtered = filterRecords(catalog, emptyState());
  assert.equal(filtered.length, catalog.length);
});

test("sanitizeTopics splits blobs and drops sentence-length labels", () => {
  const labels = sanitizeTopics([
    "untethered soft robots; soft actuators; soft sensors",
    ". Digital Health Technologies",
    "Gait variability Dynamic stability Locomotor adaptability Neural control of locomotion",
  ]);
  assert.ok(labels.includes("untethered soft robots"));
  assert.ok(labels.includes("Digital Health Technologies"));
  assert.equal(labels.some((label) => label.includes(";")), false);
  assert.equal(labels.every((label) => label.length <= 40), true);
  assert.deepEqual(splitKeywordText("Orexin/hypocretin"), ["Orexin/hypocretin"]);
});
