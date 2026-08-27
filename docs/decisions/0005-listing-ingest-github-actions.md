---
status: accepted
date: 2026-08-27
---

# Listing ingest を GitHub Actions で定期実行する

## Context and Problem Statement

APA と ScienceDirect の公式一覧は通常ブラウザでは開くが、GitHub Actions の GET は bot wall になる。Royal Society の `royalsociety.org` テーマページはこの環境から 200 で取れる。取得しない選択肢はなく、WAF 回避と Playwright は使わない。

## Decision Outcome

Chosen option: 取得経路を source ごとに分ける。

* 日次 crawl は `royal-society-themes` を有効化する。テーマページ 2 件だけを GET する。`royalsocietypublishing.org` は無効のまま。
* 週次 workflow `listing-ingest.yml` は APA の一覧 1 ページだけを GET する。Incapsula なら `source_status` に残して成功終了する。詳細ページは取らない。
* ScienceDirect は GitHub Actions から GET しない。`gha_fetch: false`。レンダリング済み HTML の HTTPS スナップショットを `workflow_dispatch` で ingest する。許可ホストは `raw.githubusercontent.com`、`gist.githubusercontent.com`、`objects.githubusercontent.com` に限る。
* browser 自動操作、UA 偽装、proxy、CAPTCHA 突破はしない。
* リポジトリ変数 `LISTING_RUNNER` があれば、その runner で listing-ingest を回す。未設定なら `ubuntu-latest`。

0003 の「bot wall の回避と browser 自動操作はしない」と、0004 の「詳細ページを巡回しない」は維持する。0004 の「GitHub Actions の定期 GET ではこの3社を有効化しない」は、Royal Society テーマページと APA の週次 1 GET についてこの決定で置き換える。

### Consequences

* Good, because Royal Society は日次で更新される
* Good, because APA は壁が外れた週から自動で正本に入る
* Good, because Elsevier を GHA から叩かずに済む
* Bad, because ubuntu-latest のままだと APA は当分 bot wall のまま
* Bad, because Elsevier の更新はスナップショット ingest が必要
