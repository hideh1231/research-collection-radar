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

* APA `calls-for-papers` は、この VM や GitHub Actions の GET では Incapsula の 212 バイト stub が返る。2026-08-27 の通常ブラウザセッションでは一覧が開き、`Last updated: August 2026`（updated_date 2026-08-18）だった。リンク付き CFP と、詳細ページ URL の無い `<li>` の両方を一覧から取る。**fields pass**
* ScienceDirect browse は GitHub Actions / この VM の GET では 403。2026-08-27 の通常ブラウザセッションでは一覧が開き、レンダリング済み DOM に 2,884 件の `/special-issue/` カード（title / journal / deadline）があった。**fields pass**。対象分野以外は `scope_pattern` と `require_domains` で落とす。Wayback の古いキャプチャは正本にしない。
* `royalsociety.org` のテーマページはこの環境から 200 で本文が返った。Call for papers 見出し配下に title とリンクがある。締切は無い。Find out more が複数 CFP で同一 URL のことがある。**pass with not_checked deadline and title-based publisher_id**
* `royalsocietypublishing.org` は Cloudflare。使わない。

### Consequences

* Good, because 詳細 2,000 件超を GET しなくてよい
* Good, because 人が保存した一覧 HTML を正本に載せられる
* Bad, because 定期 crawl だけでは APA / Elsevier は更新されない
* Bad, because Royal Society の締切は一覧に無く、OPEN.md には出ない
* 2026-08-27 のライブ一覧 ingest: Elsevier は対象分野かつ募集中 82 件。Royal Society テーマページは 3 件（締切なし、viewer のみ）。APA は通常ブラウザで開いた公式一覧から募集中を入れる。GitHub Actions の GET は引き続き無効。
