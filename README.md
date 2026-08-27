# Research Collection Radar

## Open calls

[`OPEN.md`](OPEN.md) lists open calls with a confirmed deadline. It sorts entries by deadline and shows the title, journal, research fields, collection type, and source URL. Closed calls, calls without a listed deadline, and calls whose deadline has not been checked stay in [`data/collections.jsonl`](data/collections.jsonl) but do not appear in `OPEN.md`.

## Scope

The index tracks public calls for special issues, research collections, theme issues, research topics, and related journal opportunities. It focuses on psychology, HCI, neuroscience, robotics, and HRI. A record can have more than one field.

## Data files

- `data/collections.jsonl` is the source of truth. Each line stores one opportunity, including its deadline state and change history.
- `data/source_status.json` records each crawl and deadline-enrichment result.
- `schema/collection.schema.json` defines the record format.
- `state/notification_ledger.jsonl` records new-call notifications and is not part of the public collection index.

## Sources

The enabled sources cover:

- Nature Psychology calls in Scientific Reports
- Frontiers in Psychology Research Topics
- BMC Psychology collections

The configuration in `config/sources.yml` controls source URLs, allowed hosts, pagination, and deadline checks. Disabled sources remain in the configuration for later use.

## Slack

Slack reports new open records once, after the first run. It includes records with a date, `Deadline not listed`, or `Deadline not checked`. A later deadline update does not send a second notification. `OPEN.md` has a narrower purpose: it shows only open records with a confirmed date.

Set these GitHub Actions secrets to enable Slack delivery:

- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

The bot needs the `chat:write` permission and membership in the target channel. The crawl still updates the public data when either secret is missing.

## Run locally

Use Python 3.11 or newer.

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m radar
```

Use `--offline` to skip network sources. Use `--dry-run` to skip Slack delivery and the GitHub Actions commit. Run `python -m radar --backfill-deadlines` once to check every open Frontiers record whose deadline state is `not_checked`; this command does not discover new records or send Slack notifications.

## Classification

The classifier uses journal rules and title text from `config/domains.yml`. It does not call a language model. The same file maps internal field and collection-type names to the labels shown in `OPEN.md`.

## License

MIT. Publisher rights remain with the original sources. This repository stores public metadata such as titles, journals, deadlines, and URLs; it does not republish article text.

Decision records live in [`docs/decisions/`](docs/decisions/).
