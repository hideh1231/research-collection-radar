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

The enabled sources cover:

- Nature Psychology calls in Scientific Reports
- Frontiers in Psychology, Frontiers in Robotics and AI, and Frontiers in Human Neuroscience research topics
- BMC Psychology collections
- PLOS calls for papers, via the official WordPress REST API

The configuration in `config/sources.yml` controls source URLs, allowed hosts, pagination, and deadline checks. Disabled sources remain in the configuration with a reason when GitHub Actions cannot fetch a complete public listing.

## Slack

Slack reports new open records once, after the first run. It includes records with a date, `Deadline not listed`, or `Deadline not checked`. A later deadline update does not send a second notification. `OPEN.md` has a narrower purpose: it shows only open records with a confirmed date.

Set these GitHub Actions secrets to enable Slack delivery:

- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

The bot needs the `chat:write` permission and membership in the target channel. The crawl still updates the public data when either secret is missing.

## Research keywords

Publisher keywords are copied into `topics` when a detail page lists any. Open records with no publisher keywords can be completed by an OpenAI-compatible Chat Completions API. Set all three variables or the job exits without changing records:

- `RADAR_LLM_BASE_URL` — for example `https://api.openai.com/v1`, `https://openrouter.ai/api/v1`, or `https://opencode.ai/zen/go/v1`
- `RADAR_LLM_API_KEY`
- `RADAR_LLM_MODEL` — for example `deepseek-v4-flash` on OpenCode Go, or `deepseek/deepseek-v4-flash` on OpenRouter

Only one provider is active. There is no automatic fallback. Scheduled runs enrich at most 100 records; a manual run can enrich 500.

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

The classifier uses journal rules and title text from `config/domains.yml`. Publisher keywords and the optional LLM pass fill `topics`. Alias unification lives in `config/topic_aliases.yml` and does not merge unknown terms.

## License

MIT. Publisher rights remain with the original sources. This repository stores public metadata such as titles, journals, deadlines, and image URLs; it does not republish article text or image files.

Decision records live in [`docs/decisions/`](docs/decisions/).
