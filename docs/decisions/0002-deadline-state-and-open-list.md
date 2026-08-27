---
status: accepted
date: 2026-08-26
---

# 締切状態を保存し締切付き公募だけを一覧に出す

## Context and Problem Statement

募集中 469 件のうち、Frontiers in Psychology の Research Topic 354 件は締切が空である。現行処理は新着だけを最大 60 件まで個別確認し、取得済みの締切も次回の一覧取得で消す。`deadline: null` だけでは、未確認と掲載なしを区別できない。`OPEN.md` は締切を選ぶための一覧とし、締切が分からない案件は正本と Slack に残す。

## Considered Options

* 締切状態を三つに分け、既存案件を間隔を空けて補完し、締切付きだけを `OPEN.md` に出す
* 締切状態を増やさず、空欄を文字で示す
* 締切がない案件を正本からも除外する

## Decision Outcome

Chosen option: "締切状態を三つに分け、既存案件を間隔を空けて補完し、締切付きだけを `OPEN.md` に出す", because 未確認と掲載なしを区別しながら、読者が締切順の案件だけを選べる。Frontiers の締切を新着だけ確認する 0001 の方針と、募集中なら締切なしも `OPEN.md` に出す方針は、この決定で置き換える。

### Consequences

* Good, because `OPEN.md` の締切欄に空欄が残らない
* Good, because 研究分野と企画種別を一覧で確認できる
* Bad, because Frontiers の個別ページを定期確認する通信と実行時間が増える
* Bad, because 締切なしの新着は Slack に出ても `OPEN.md` には出ない
