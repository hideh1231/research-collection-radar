# Research Collection Radar

## Open calls

[`OPEN.md`](OPEN.md) lists open calls with a confirmed deadline. It sorts entries by deadline and shows the title, journal, research fields, collection type, and source URL.

The GitHub Pages viewer in [`site/`](site/) lists every open call, including those whose deadline is not listed or not yet checked. It searches title, summary, journal, fields, and topics. JSONL remains the source of truth; `site/data/collections.json` is generated from it.

Closed calls stay in [`data/collections.jsonl`](data/collections.jsonl).

## Scope

The index tracks public calls for special issues, research collections, theme issues, research topics, and related journal opportunities. It focuses on psychology, HCI, neuroscience, robotics, and HRI. A record can have more than one field.

## Data files

- `data/collections.jsonl` is the source of truth. Each line stores one opportunity, including its deadline state, journals, publisher keywords, and change history.
- `data/source_status.json` records each crawl, detail-page, and topic-enrichment result.
- `schema/collection.schema.json` defines the record format.
- `state/notification_ledger.jsonl` records new-call notifications and is not part of the public collection index.
- `site/` is the GitHub Pages viewer. Fonts are served from the repository with their licenses.

## Sources

The index covers psychology, HCI, neuroscience, robotics, and HRI. Enabled sources are public listings that GitHub Actions can finish without a bot wall:

- Nature Portfolio: Scientific Reports, Communications Psychology, Nature Communications, and Communications Biology calls. Nature Neuroscience collections that are open for submissions are merged onto the same collection id.
- Frontiers research topics, including Neuroergonomics, Ethology, Ecology and Evolution, and Veterinary Science
- Springer Nature BMC collections and Springer Link `/journal/{id}/collections` for watched journals
- PLOS calls for papers, via the official WordPress REST API
- Domestic listings: Journal of Robotics and Mechatronics, VRSJ special issues, IPSJ CFP list, JSKE

ScienceDirect と APA は日次 crawl では disabled のまま。Royal Society の `royalsociety.org` テーマページは日次 crawl が取る。週次の [`listing-ingest.yml`](.github/workflows/listing-ingest.yml) が ubuntu-latest 上の headed Chrome で APA、ScienceDirect、APS、Science Robotics、T&F Author Services、SAGE、PNAS、PNAS Nexus、JOSA A、監視 Wiley 誌の一覧 1 ページを開き、レンダリング済み HTML を ingest する。stealth や CAPTCHA 突破はしない。壁なら status だけ残す。スナップショット URL を `workflow_dispatch` に渡す経路も残っている。

```text
python -m pip install -e ".[listing]"
python -m playwright install chromium
python -m radar --render-listings --out-dir listing-html --only apa-cfp --only sciencedirect-cfp
python -m radar --open-only --ingest-rendered listing-html
```

`--open-only` は締切切れを落とす。ScienceDirect / T&F / SAGE / APS のハブは `config/journals.yml` の監視誌名に一致したカードだけ残す。Decision records: [`docs/decisions/0004-listing-snapshot-coverage.md`](docs/decisions/0004-listing-snapshot-coverage.md), [`docs/decisions/0005-listing-ingest-github-actions.md`](docs/decisions/0005-listing-ingest-github-actions.md), [`docs/decisions/0006-watched-journals-and-listing-hosts.md`](docs/decisions/0006-watched-journals-and-listing-hosts.md).

The viewer is the GitHub Pages site at `https://hideh1231.github.io/research-collection-radar/`.

## Slack

Slack reports new open records once, after the first run. It includes records with a date, `Deadline not listed`, or `Deadline not checked`. A later deadline update does not send a second notification. `OPEN.md` has a narrower purpose: it shows only open records with a confirmed date.

Set these GitHub Actions secrets to enable Slack delivery:

- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

The bot needs the `chat:write` permission and membership in the target channel. The crawl still updates the public data when either secret is missing.

## Research keywords

Publisher keywords are copied into `topics` when a detail page lists any. Open records also receive existing catalog labels when the title or summary contains them (aliases such as AI, plus topics that already appear on at least two open records). Open records with no publisher keywords can be completed by an OpenAI-compatible Chat Completions API. Set all three variables or the LLM pass exits; catalog overlay still runs:

- `RADAR_LLM_BASE_URL` — for example `https://api.openai.com/v1`, `https://openrouter.ai/api/v1`, or `https://opencode.ai/zen/go/v1`
- `RADAR_LLM_API_KEY`
- `RADAR_LLM_MODEL` — for example `deepseek-v4-flash` on OpenCode Go, or `deepseek/deepseek-v4-flash` on OpenRouter

Only one provider is active. There is no automatic fallback. Scheduled runs enrich at most 100 records; a manual run can enrich 500. The prompt prefers existing labels. Descriptions (`summary`) come from publisher pages, not the LLM.

## Run locally

Use Python 3.11 or newer.

```text
python -m pip install -e ".[dev]"
python -m pytest
node --test tests/js/test_viewer.mjs
python -m radar
python -m radar --build-site
```

Use `--offline` to skip network sources. Use `--dry-run` to skip Slack delivery and the GitHub Actions commit. Run `python -m radar --backfill-deadlines` once to check every open Frontiers record whose deadline state is `not_checked`; this command does not discover new records or send Slack notifications. Run `python -m radar --enrich-topics` after crawl if LLM settings are present.

Serve the viewer with `python -m http.server -d site 8000`.

## Classification

The classifier uses journal rules and title text from `config/domains.yml`. Publisher keywords, catalog overlay, and the optional LLM pass fill `topics`. Alias unification lives in `config/topic_aliases.yml` and does not merge unknown terms.

## License

MIT. Publisher rights remain with the original sources. This repository stores public metadata such as titles, journals, deadlines, and image URLs; it does not republish article text or image files.

Decision records live in [`docs/decisions/`](docs/decisions/).
