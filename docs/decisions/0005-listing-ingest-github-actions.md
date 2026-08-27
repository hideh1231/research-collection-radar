---
status: accepted
date: 2026-08-27
---

# Listing ingest を GitHub Actions で定期実行する

## Context and Problem Statement

APA と ScienceDirect の公式一覧は通常ブラウザでは開くが、GitHub Actions の生 GET は bot wall になる。取得しない選択肢はなく、WAF 回避・UA 偽装・CAPTCHA 突破・proxy は使わない。詳細ページは巡回しない。

## Decision Outcome

Chosen option: ubuntu-latest 上で **Chromium を起動し、一覧 1 ページだけをレンダリングして HTML を ingest する**。これはコンピュータ上の通常ブラウザで一覧を保存したのと同じ経路。stealth プラグインは使わない。CAPTCHA が残ったらそこで止める。

* 週次 workflow `listing-ingest.yml` が **Google Chrome（headed、xvfb）** で APA の calls-for-papers と ScienceDirect の browse を各 1 ページ開く。cookie バナーは Accept する。一覧マーカーが出たら HTML を保存して `--open-only --ingest-rendered` する。
* Playwright 付属の headless Chromium は同じ IP でも壁になる。通常の Chrome バイナリを `channel="chrome"` で起動する。stealth プラグインは使わない。
* 壁や CAPTCHA ならその source は ingest せず、ジョブは成功のまま終わる。保存できた HTML は artifact に残す。
* 日次 crawl の生 GET では APA / ScienceDirect を有効化しない。Royal Society テーマページは日次 GET のまま。
* `workflow_dispatch` で GitHub raw / gist のスナップショット URL を渡す経路は残す。
* Playwright stealth、Googlebot 偽装、proxy、CAPTCHA 突破はしない。

0003 の「browser 自動操作はしない」は、**一覧 1 ページを通常 Chromium で保存する操作**についてこの決定で置き換える。詳細ページ巡回と bot wall 回避はしない。

### Consequences

* Good, because Actions でも人がブラウザで保存したのと同じ HTML を正本に入れられる
* Good, because 詳細 2,000 件超を GET しなくてよい
* Bad, because GitHub の IP では Chromium でも壁が残ることがある
* Bad, because Playwright と Chromium のインストールで週次ジョブが重くなる
