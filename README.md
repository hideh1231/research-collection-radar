# Research Collection Radar

A public, automated index of special issues, research collections, theme issues, research topics, and related calls for papers across psychology, HCI, robotics, HRI, and adjacent fields.

学術雑誌が公開している特集・Collection・Research Topic などの公募を集め、公開 GitHub リポジトリを正本にする。人間向けの一覧は締切順の `OPEN.md`。Slack は 2 日目以降の新規だけを 1 通にまとめる。

## 正本

- `data/collections.jsonl` — 1 行 1 件。閉じた案件も `status=closed` で残す
- `OPEN.md` — 募集中だけ。締切順。締切が無い行は末尾
- `data/source_status.json` — 取得の成否。変更が無くても更新する

各 Collection の権利は元の出版社にある。このリポジトリが持つのは題名・雑誌・締切・URL などの公開事実である。本文は転載しない。

## いま有効な取得元

- Nature / Scientific Reports の Psychology 公募
- Frontiers in Psychology の Research Topics
- BMC Psychology の Collection 一覧

ScienceDirect・APA・Royal Society はボット対策でローカルから読めなかったので毎日の実行には載せていない。PLOS は案内リンクしか取れなかったので外している。

GitHub Actions が UTC 21:17（JST 6:17）に回す。秘密情報は次の 2 つだけをリポジトリの Secrets に置く。

- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

bot の権限は `chat:write` だけでよい。通知先の private チャンネルに bot を入れる。Secret が無い日はデータだけ更新し、通知は飛ばす。初回は送信記録だけ書き、Slack は送らない。

## 手元で回す

Python 3.11 以降。

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m radar
```

`--dry-run` は通知しない。`--offline` は取得を飛ばす。

## 分野

心理・HCI・神経科学・ロボティクス・HRI。1 件に複数付く。分類は雑誌名簿と題名の語だけで、言語モデルは使わない。

## ライセンス

MIT。判断の記録は `docs/decisions/0001-github-jsonl-open-md-slack.md`。
