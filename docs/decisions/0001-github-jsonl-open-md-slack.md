---
status: accepted
date: 2026-08-26
---

# 公開 GitHub の JSONL を正本にする

## Context and Problem Statement

学術出版社が公開している Collection / Special Issue / Research Topic 等の公募を集め、新規を知らせ、締切順に見られるようにしたい。データは公開してよく、更新は1日1回程度、件数は当面数百〜数千である。専用の常時データベース、Notion、言語モデル必須の分類は、この条件では運用と秘密情報が増える。初版で複数出版社と閲覧用の静的ページまで作ると、通知が届く前に部品が増える。

対象外: 未公開の研究テーマや投稿予定などの private な注釈、学会の一般公募の網羅、GitHub Issue / Project による一件管理、初版の OpenRouter と締切 Slack。

## Considered Options

* 公開 GitHub リポジトリの JSONL を正本にし、OPEN.md を締切順の一覧、Slack を新着のまとめ通知にする
* Notion を正本にする
* 1 件を 1 GitHub Issue または Project にする
* 初版から GitHub Pages で列並び替えする

## Decision Outcome

Chosen option: "公開 GitHub リポジトリの JSONL を正本にし、OPEN.md を締切順の一覧、Slack を新着のまとめ通知にする", because 公開配布と履歴と外部からの改善が同じ場所に載り、秘密情報は Slack の token とチャンネル ID だけで済む。締切の意識は OPEN.md が担い、Slack は割り込みに限る。列クリックの並び替えは正本を変えずに後から静的ページを足せる。

リポジトリ名は `research-collection-radar`。置き場所は `github.com/hideh1231/research-collection-radar`。ライセンスは MIT。分野は心理・HCI・神経科学・ロボティクス・HRI を第一級とし、1 件に複数付けてよい。初版の分類は雑誌名簿と題名の語だけとし、OpenRouter は使わない。

最初に有効化する取得元は Nature の Psychology 公募である。一覧に募集状態と締切が出る。Frontiers は 2 本目とし、締切は新規だけ個別ページから取る。ScienceDirect・APA・Royal Society などボット対策がある相手は、GitHub Actions で取れてから毎日の実行に載せる。

閉じた案件は正本から消さず `status=closed` で残す。OPEN.md は募集中だけ出す。毎日全件の `last_seen` は更新しない。初回実行は送信記録だけ書き Slack は送らない。2 回目以降の新規は 1 通にまとめる。ページングを最後まで辿れない取得は失敗とする。取得が無い日も `data/source_status.json` を更新する。

### Consequences

* Good, because clone と raw と Git 履歴がそのまま公開データの監査になる
* Good, because Slack を入れなくても OPEN.md で締切順に読める
* Good, because 取得元を後から足しても正本の形と通知の管を変えなくてよい
* Bad, because GitHub 上の Markdown 表は列クリックで並び替えできない
* Bad, because GitHub Actions の IP は出版社のボット対策に止められ、ローカルで取れた取得元が毎日の実行では落ちることがある
* Bad, because 初版は Nature Psychology に偏り、HRI やロボティクスの公募は Frontiers 以降まで薄い
