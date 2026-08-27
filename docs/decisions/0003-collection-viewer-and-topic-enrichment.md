---
status: accepted
date: 2026-08-27
---

# Collection viewer、取得元拡張、研究キーワード補完

## Context and Problem Statement

正本の JSONL と `OPEN.md` は、締切が分かっている募集中案件を読む用途には足りる。一方で、締切未確認の募集中案件は一覧に出ず、title に状態や編集者が混ざり、研究キーワードもなく、GitHub 上では検索や絞り込みができない。Frontiers も Psychology 以外の対象分野 journal がまだ無い。言語モデルを分類の必須条件にはしない、という 0001 の方針は維持したまま、閲覧面と取得範囲とキーワードだけを足したい。

## Considered Options

* JSONL を正本のまま、GitHub Pages の静的 viewer を足し、Frontiers を journal 単位で広げ、publisher keyword を優先して LLM は不足分だけ補う
* Notion や Issue を閲覧面にする
* 初版から複数 LLM provider を自動切替する
* 画像ファイルも repository に複製する

## Decision Outcome

Chosen option: "JSONL を正本のまま、GitHub Pages の静的 viewer を足し、Frontiers を journal 単位で広げ、publisher keyword を優先して LLM は不足分だけ補う", because 正本と Slack の契約を変えずに、投稿先を探す索引と分野の穴とキーワード不足を同じ変更で解ける。

0001 のうち「初版から GitHub Pages で列並び替えする」を見送った部分と、分類に言語モデルを使わない部分は、この決定で部分的に置き換える。JSONL を正本にし、Slack を新着通知に使い、`OPEN.md` を締切付き募集中の一覧にする方針は維持する。viewer は募集中の全件を対象にし、締切の有無では除外しない。

### Frontiers の title と一件化

一覧の title は `h2.CardResearchTopic__title` だけから取る。状態、編集者、閲覧数、記事数は title に入れない。title 要素がない card は不正な部分取得とし、その一覧は成功にしない。URL slug から title を推測しない。

同一 Research Topic は topic ID を `publisher_id` にして 1 件へ統合する。既存の Frontiers ID は維持し、Slack の再通知を防ぐ。`journal` は主 journal、`journals` は参加 journal を含む全 journal、複数一覧の source key は `source_keys` に入れる。

### 詳細 metadata

詳細ページから企画説明、publisher keyword、`og:image`、主 journal、参加 journal を取る。summary は企画説明の先頭段落を最大 1,000 文字まで保存する。投稿料金、編集者、navigation は使わない。途中で切れた `og:description` は保存しない。画像は URL だけ保存し、ファイルは repository へ複製しない。

確認日時だけの更新は `content_hash` に入れない。title、summary、journals、publisher keyword、topics、image URL の変更は入れる。

締切と詳細 metadata の queue は source 一件前提ではなく、Frontiers の publisher ID 前提にする。

### GitHub Pages viewer

`site/` に素の HTML、CSS、JavaScript と、正本 JSONL から生成した公開用 JSON を置く。JSONL は正本のままとする。見た目は「次に投稿する企画を探す research index」とし、装飾目的の大きな hero や常時 animation は置かない。Pages workflow は `site/` を成果物として公開し、crawl と LLM workflow の commit のあとに再公開する。

### 取得元

第1段階で Frontiers in Robotics and AI と Frontiers in Human Neuroscience を有効化する。第2段階の PLOS は、公式 HTML の Calls for Papers 一覧が完了しない一方、公式 WordPress REST API で title、URL、stable ID、ページング完了を確認できた場合に限り有効化する。募集状態は API に open/closed が無いので、公式本文の締切から導く。第3段階の ScienceDirect、APA、Royal Society は、公開 HTML / 公式 API / feed / sitemap だけで GitHub Actions から安定取得できないものは無効のままにし、理由を `source_status.json` に残す。bot wall の回避と browser 自動操作はしない。

新しい source は一覧の完全性を必須とする。締切が取れなくても `not_checked` で収録してよい。`not_listed` にするのは、詳細ページを正常取得し、締切表記がないことを確認したあとに限る。

### 研究キーワード

publisher keyword が 1 個以上あれば正規化して `topics` に使い、LLM は呼ばない。0 個の募集中だけを LLM queue に入れる。入力は record ID、title、主 journal と参加 journal、summary、domains に限る。出力は英語の通称 3〜6 個とし、確認済み alias だけを設定ファイルで統一する。未知の語は自動統合しない。

open 件では、既存の topic 語彙（open で2回以上）と alias（HCI / HRI / VR / XR / AI / LLM など）が title または summary に単語境界で出たとき、それを `topics` の末尾に足す。上限は 8。`research` / `study` / `health` / `care` / `review` と一度きりの publisher 句は付けない。`topics_method` は変えない。LLM プロンプトにはこの語彙の頻度上位を最大 80 個渡し、ある通称はそれを使う。

接続は `RADAR_LLM_BASE_URL`、`RADAR_LLM_API_KEY`、`RADAR_LLM_MODEL` に統一する。単一 provider だけを有効にし、自動 fallback はしない。OpenAI、OpenRouter、OpenCode Go は `/chat/completions` の共通部分だけを使う。LLM 補完は crawl と別 workflow にし、同じ `concurrency.group` で直列化する。設定が無い場合は LLM を skip する。catalog overlay は crawl と `--enrich-topics` の両方で API なしでも動く。

Frontiers の詳細取得は 1 日 400 件まで。`remaining` は daily_limit で切らず、未取得の実件数を出す。summary は出版社ページから取り、LLM では書かない。

Viewer の Fields / Type / Deadline / Journal / Topics は複数選択で、空選択は All。All を明示する。募集タイトルの URL は新しいタブで開く。

### Consequences

* Good, because 締切なしの募集中も viewer で探せる
* Good, because Frontiers の同一 topic を journal 横断で 1 件にでき、既存 ID を壊さない
* Good, because publisher keyword がある案件では LLM を使わずに済む
* Bad, because Frontiers の完全な一覧取得はページ数が増え、詳細確認の通信も増える
* Bad, because GitHub Actions から取れない取得元は、公開 HTML があるだけでは有効化できない
* Bad, because LLM 補完は API 設定と別 workflow の成功に依存する
