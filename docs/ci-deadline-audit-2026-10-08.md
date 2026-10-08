# CI and deadline verification audit (2026-10-08)

Scope: repair incomplete detail verification, refresh due Frontiers records, resolve the stale Nature submission link, and verify the public viewer. Slack delivery and LLM enrichment are excluded at the user's request. Existing disabled publisher sources remain subject to their documented access limits.

## Code and CI

- Baseline main: `1fc836510689af2412df9e58a328ac7baa5dbb82`.
- [PR #18](https://github.com/hideh1231/research-collection-radar/pull/18) records the code and data changes.
- 245 Python tests and 12 JavaScript tests passed locally. Hosted Test CI also passed on the repair branch.
- [Hosted live listing validation](https://github.com/hideh1231/research-collection-radar/actions/runs/37743685970): Royal Society returned 3 calls from 2 pages; Nature Humanities returned 44 calls.
- [Hosted Nature detail validation](https://github.com/hideh1231/research-collection-radar/actions/runs/37743690230): 1 checked, 1 updated, 0 remaining, no errors.

## Live Frontiers refresh

- Attempted every selected due record: 601 / 601.
- Verified page identity for 592; parsed exact dates on 488; retained a prior date on 30; checked without a date 74.
- Failed 9; unavailable pages 9; pending 9; parse warnings 30.
- A 404/410 no longer contributes to the publisher outage cutoff. 403, repeated 429, and repeated transport/server failures still stop the pass.
- The next bounded pass prioritizes untouched work before previously failed URLs. Successful retries clear their saved errors.
- A failed check preserves the complete previous record. No missing page is labelled closed or checked without a date.
- Parse warnings are distinct from HTTP failures. In particular, a successfully identified page can no longer show an exact date; the earlier date is retained rather than erased. Such a retained date is not evidence that its value was reconfirmed in this pass.
- `python -m radar --check-frontiers --limit 10000 --dry-run` reproduces the full due-detail pass. The command returns nonzero while work is incomplete; dry-run still writes local artifacts.

## Nature submission link

- The official `/collections/cedideagbe/how-to-submit` page returned 404 in a normal browser. The same collection root loaded successfully and matched the saved title.
- The root contains no submission panel, manuscript deadline, or submission link. The record is now status `unknown`, deadline status `not_listed`, with no invented date. It is preserved in JSONL and excluded from open calls.
- The fallback verifies only the same collection identity. Redirects to another collection and challenge pages remain failures.
- Browser HTML SHA256: `1bf97fd347b39a014f02213d40a6290e30f91511409bf45707d77a1fb8a94946`.

## Royal Society and remaining external limits

- The official theme listings confirm the three calls but do not supply exact manuscript deadlines. Both linked publishing-platform pages return 403. The RSOS page also returned 403 in a normal browser; web extraction returned 403 for both pages.
- These three calls remain `not_checked`. The absence of a date in the accessible overview is not proof that no deadline exists.
- Two RSOS summaries were previously shifted by the introductory paragraph. They now come from the paragraphs following each corresponding bold title.

| Record | Result | Previous confirmed deadline | URL |
| --- | --- | --- | --- |
| `frontiers-25cdcb330a` | http 404 | 2026-08-31 | [official page](https://frontiersin.org/research-topics/73981/mental-health-and-suicide-prevention-in-sensory-impairment-populations-volume-ii) |
| `frontiers-26749dbc9f` | http 404 | 2027-02-26 | [official page](https://frontiersin.org/research-topics/79710/towards-inclusive-education-with-interactive-ai-and-social-robotics) |
| `frontiers-3da580dc8f` | http 404 | 2026-08-30 | [official page](https://frontiersin.org/research-topics/72145/bio-inspired-robots-at-the-air-water-interface) |
| `frontiers-7844762ae0` | http 404 | 2027-01-16 | [official page](https://frontiersin.org/research-topics/82861/epigenetic-immune-regulations-in-neurological-disorders) |
| `frontiers-98eb7c82b6` | http 404 | 2026-10-21 | [official page](https://frontiersin.org/research-topics/77534/lipid-metabolism-and-transport-in-neuronal-and-glial-cell-function-and-dysfunction) |
| `frontiers-ed8601a844` | http 404 | 2026-12-15 | [official page](https://frontiersin.org/research-topics/80992/new-insights-into-mitochondria-induced-neuroimmune-disorderfrom-mechanisms-to-phenotypes) |
| `frontiers-f1ead1ca94` | http 404 | 2026-09-25 | [official page](https://frontiersin.org/research-topics/76957/aging-estrogen-nutrition-and-neuroinflammation-in-womens-cognitive-decline-and-neurodegeneration) |
| `frontiers-f903b1c68e` | http 404 | 2027-03-19 | [official page](https://frontiersin.org/research-topics/85460/human-performance-in-the-age-of-ai-neurocognitive-mechanisms-of-learning-decision-making-and-adaptive-human-ai-collaboration) |
| `frontiers-psychology-a866dee1b1` | http 404 | 2027-01-20 | [official page](https://frontiersin.org/research-topics/77027/ai-and-the-future-of-well-being-navigating-the-promise-and-perils-of-positive-psychology) |
| `royal-society-themes-36f43f66b8` | HTTP 403 on linked detail page | unconfirmed | [official page](https://royalsocietypublishing.org/rsos/pages/special-collections) |
| `royal-society-themes-5fd81fc0fa` | HTTP 403 on linked detail page | unconfirmed | [official page](https://royalsocietypublishing.org/rsos/pages/special-collections) |
| `royal-society-themes-fb2041eba2` | HTTP 403 on linked detail page | unconfirmed | [official page](https://royalsocietypublishing.org/rsob/pages/special-features) |

## Data and viewer checks

- Preserved all 14243 record IDs and first-seen dates. No previously confirmed deadline was erased.
- Generated viewer data contains 3063 open calls, including 3 with unchecked deadlines.
- Public viewer was tested in a normal browser: full list loaded; searching robotics returned 208 calls; title sorting changed the URL state; switching to Table rendered 48 rows with the Table button pressed.
- The Pages workflow builds schema-validated main data after a successful or partially failed writer run. A partial failure therefore does not prevent publishing already saved healthy data.
- CI now displays saved verification timestamps and pending counts, and emits a warning for failed Frontiers details. A green listing crawl is not presented as full detail verification.
