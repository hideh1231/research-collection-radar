---
status: accepted
date: 2026-08-27
---

# APA / Royal Society / Elsevier は一覧スナップショットから取る

## Context and Problem Statement

GitHub Actions から APA、Royal Society 出版サイト、ScienceDirect の HTML を取ると bot wall になる。詳細ページを巡回すれば負荷と回避の問題がさらに増える。取得しない選択肢はなく、公式一覧だけで正本の title / journal / url / deadline が揃うかを先に確認する必要があった。

## Decision Outcome

Chosen option: 公式一覧のレンダリング済み HTML を parse し、`python -m radar --ingest-html KEY=PATH` で JSONL に入れる。GitHub Actions の定期 GET ではこの3社を有効化しない。詳細ページは取らない。

Coverage probe（2026-08-27）:

* APA `calls-for-papers` は Incapsula。Wayback の 2025-10-18 スナップショットでは、雑誌モジュールごとにユニークな CFP URL と manuscript deadline がある。**pass**
* ScienceDirect browse は 403。Wayback の 2025-09-12 スナップショットでは `li.publication` と埋め込み JSON に title / journal / `/special-issue/{id}` / ISO deadline が約 2,470 件ある。**fields pass**。対象分野以外は `require_domains` で落とす。
* `royalsociety.org` のテーマページはこの環境から 200 で本文が返った。Call for papers 見出し配下に title とリンクがある。締切は無い。Find out more が複数 CFP で同一 URL のことがある。**pass with not_checked deadline and title-based publisher_id**
* `royalsocietypublishing.org` は Cloudflare。使わない。

### Consequences

* Good, because 詳細 2,000 件超を GET しなくてよい
* Good, because 人が保存した一覧 HTML を正本に載せられる
* Bad, because 定期 crawl だけでは APA / Elsevier は更新されない
* Bad, because Royal Society の締切は一覧に無く、OPEN.md には出ない
