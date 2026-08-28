---
status: accepted
date: 2026-08-27
---

# 監視誌 allowlist と listing ingest の延長

## Context and Problem Statement

ScienceDirect の browse は対象分野キーワードで落としていたため、Vision Research など監視誌の特集が正本に入らなかった。T&F / SAGE / APS / Science Robotics / PNAS 系は公式一覧があるが日次 GET では壁になる。

## Decision Outcome

Chosen option: `config/journals.yml` の誌名（と alias）に一致したら、題名が psychology でなくても残す。ScienceDirect の `scope_pattern` / `require_domains` はやめる。ハブ一覧（Elsevier, T&F, SAGE, APS）だけ `require_watched_journal` する。

週次 listing-ingest は APA / ScienceDirect に加え、APS calls、Science Robotics、T&F Author Services、SAGE SI ハブ、PNAS、PNAS Nexus、JOSA A、監視 Wiley 誌の誌別 CFP を headed Chrome で 1 ページずつ試す。壁ならそのソースは ingest せず status だけ残す。

Nature の Scientific Reports は Psychology subject ではなく誌の CFP 全件。Communications Psychology / Nature Communications / Communications Biology も誌単位。Nature Neuroscience は `/neuro/calls-for-papers` が無く、`/neuro/collections` のうち Submission status が Open のものだけ取る。締切はそのページに無いので、同一 collection id を Communications Biology / Nature Communications / Scientific Reports の CFP とマージして誌名だけ足す。Frontiers 未収録誌と Springer `/collections`、国内の JRM / VRSJ / IPSJ / JSKE は日次 GET。Open Mind と Cognitive Science は公開の募集一覧が無く、クローラから見ると壁になるので専用ソースにはしない。

### Consequences

* Good, because 監視誌の見逃しが減る
* Bad, because Scientific Reports と Nature Communications は化学などの collection も入る。見せ分けは viewer の Journal / Topics
* Bad, because Chrome ingest のホストが増え、週次ジョブが重くなる
