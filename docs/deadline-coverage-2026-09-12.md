# 締切と取得対象誌の点検（2026-09-12）

「設定済み」「一覧で照合済み」「個別ページで確認済み」は別の状態です。
今回の点検でも、全対象誌の全公募を漏れなく確認できたとは言えません。
修正後の公開データではDeadline not checkedが76件から4件になりました。
締切補完・締切なしの確認に加え、受付終了、受付状態不明、誤登録の表示を修正した結果です。

## APA

[公式公募一覧](https://www.apa.org/pubs/journals/resources/calls-for-papers)の取得HTMLを解析すると48件です。
対象誌の設定は6誌ですが、APAの取得処理は対象誌で絞らず一覧全体を収集します。
掲載中の37件のうち、12件には公式一覧に「no submission deadline」と明記されていました。
その記載を保存していなかったため、Deadline not checkedになっていました。今回修正しました。
日付が見当たらないだけの募集は、この理由で確認済みにはしません。

| 対象誌 | 今回の確認結果 |
| --- | --- |
| American Psychologist | 取得した一覧に該当項目なし。個別公募ページはアクセス制限があり、募集の不存在は未確認 |
| Psychological Methods | Tutorials in Psychological Methodsの一般公募あり。特集ではない一般公募として従来の除外対象 |
| Journal of Experimental Psychology: Human Perception and Performance | 取得した一覧に該当項目なし。個別公募ページはアクセス制限があり、募集の不存在は未確認 |
| Journal of Experimental Psychology: Learning, Memory, and Cognition | Conflict adaptation、原稿締切2026-10-01 |
| Journal of Experimental Psychology: Animal Learning and Cognition | Avian cognition、原稿締切2026-10-15（意向表明締切とは区別） |
| Psychological Bulletin | 系統的レビューのデータベースを活用する特集欄。締切なしの明記を確認 |

Psychological Methodsの一般公募は[公式案内](https://www.apa.org/pubs/journals/met/call-for-papers-tutorials)で確認できます。
HTTP 200でもIncapsulaの制限画面を返す個別ページがあるため、200だけを確認成功の根拠にはしていません。

## ScienceDirect / Elsevier

GitHub Actions実行34682753242で取得した[公式一覧](https://www.sciencedirect.com/browse/calls-for-papers)のHTMLから2,378件を解析しました。
修正後の対象40誌との照合では47件、うち締切前の募集は38件でした。
既存の公開データには、過去の取得分なども含め98件のElsevier募集があり、98件すべてに締切があります。
これは個別誌の公募を網羅した証明にはなりません。現在の個別ページ取得では403も発生しています。

Cognition and InstructionはElsevierではなくTaylor & Francisです。
[出版社の公式ページ](https://www.tandfonline.com/toc/hcgi20/current)に合わせ、出版社設定とAPI取得対象を修正しました。

| 対象誌 | 一覧内の件数 | 締切前の件数 | 確認範囲 |
| --- | ---: | ---: | --- |
| Vision Research | 3 | 3 | 一覧で確認 |
| Hearing Research | 2 | 2 | 一覧で確認 |
| Cognition | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Cortex | 3 | 3 | 一覧で確認 |
| Computers in Human Behavior | 1 | 1 | 一覧で確認 |
| International Journal of Human-Computer Studies | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Robotics and Autonomous Systems | 1 | 1 | 一覧で確認 |
| Behavioural Brain Research | 1 | 1 | 一覧で確認 |
| Neurobiology of Learning and Memory | 1 | 1 | 一覧で確認 |
| Animal Behaviour | 1 | 1 | 一覧で確認 |
| Acta Psychologica | 1 | 1 | 一覧で確認 |
| Consciousness and Cognition | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| New Ideas in Psychology | 1 | 1 | 一覧で確認 |
| Brain and Cognition | 2 | 1 | 一覧で確認 |
| Neuropsychologia | 3 | 3 | 一覧で確認 |
| Cognitive Systems Research | 1 | 1 | 一覧で確認 |
| NeuroImage | 7 | 3 | 一覧で確認 |
| NeuroImage Clinical | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Experimental Neurology | 1 | 0 | 一覧で確認 |
| Neuroscience Letters | 3 | 2 | 一覧で確認 |
| Molecular and Cellular Neuroscience | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Behavioural Processes | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Applied Animal Behaviour Science | 2 | 2 | 一覧で確認 |
| Hormones and Behavior | 2 | 2 | 一覧で確認 |
| Biomimetic Intelligence and Robotics | 2 | 2 | 一覧で確認 |
| Neuroscience | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Experimental Eye Research | 1 | 1 | 一覧で確認 |
| Journal of Neuroscience Methods | 1 | 1 | 一覧で確認 |
| Current Opinion in Behavioral Sciences | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Current Opinion in Neurobiology | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Trends in Cognitive Sciences | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Trends in Neurosciences | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Cognitive Psychology | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Journal of Memory and Language | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Neural Networks | 1 | 1 | 一覧で確認 |
| Neurocomputing | 5 | 3 | 一覧で確認 |
| Biological Psychology | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| International Journal of Psychophysiology | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |
| Journal of Experimental Social Psychology | 1 | 1 | 一覧で確認 |
| Organizational Behavior and Human Decision Processes | 0 | 0 | 一覧に掲載なし・個別ページ未検証 |

件数0は「今回の一覧に掲載されていない」という意味です。「募集が存在しない」とは判断していません。

## SAGE

設定対象6誌の個別ページを確認しました。従来の保存データは0件でした。
総合一覧と通常のHTTP取得はアクセス制限が残っています。
今回見つかった募集中の2件は、公式PDF/DOCXを定期取得する処理を追加しました。

| 対象誌 | 確認した公式ページ・資料 | 結果 |
| --- | --- | --- |
| Quarterly Journal of Experimental Psychology | [誌面](https://journals.sagepub.com/home/qjp)、[公式PDF](https://journals.sagepub.com/pb-assets/cmscontent/QJP/Damjanovic_SI_2026-1786967343257.pdf) | Cultural Relativity Hypothesisを追加。原稿締切2027-04-30。意向表明は2026-11-30 |
| Adaptive Behavior | [誌面](https://journals.sagepub.com/home/adb)、[公式DOCX](https://journals.sagepub.com/pb-assets/cmscontent/adb/SI%20New-1781664003197.docx) | Neurophenomenologyを追加。原稿締切2026-11-01 |
| i-Perception | [公募一覧](https://journals.sagepub.com/page/ipe/call-for-papers/index) | The Perception of Numberの締切は2026-07-31。現在は終了 |
| Perception | [誌面](https://journals.sagepub.com/home/pec) | 今回確認したページに特集公募なし |
| Psychological Science | [誌面](https://journals.sagepub.com/home/pss) | 今回確認したページに特集公募なし。編集者募集・既刊論文集は対象外 |
| Personality and Social Psychology Bulletin | [誌面](https://journals.sagepub.com/home/psp) | 今回確認したページに特集公募なし。既刊のresearch collectionは公募ではない |

新規公募をSAGE全6誌から自動発見する仕組みの網羅性は未検証です。
追加した2件の資料の締切は毎日読み直しますが、新しい資料URLを自動発見する機能ではありません。

## 締切チェックの変更と影響

対象は収集処理、CLI、定期Crawl、保存データ、OPEN.md、公開画面です。
`python -m radar --check-deadlines`を追加し、通常のCrawl後にも実行します。
未確認のNature・Springer・JSKE詳細を優先し、確認済みで日付のないページは7日後に再確認します。既定上限は1回100件です。

中心命題は、(1)当該募集の公式記載を確認できた場合だけ締切状態を更新すること、(2)取得失敗で既存の締切・ID・初回発見日を失わないことです。

### cleared checks

- Nature・Springerの実ページ52件中51件を確認。22件は受付終了、19件は現在の受付状態を確認できずunknownに修正。残りは募集中と確認できたページです。
- Natureの改題したcollectionも同じURLと投稿受付欄で照合。開催・掲載日を論文締切に採用しません。
- JSKEの延長後の締切、VRSJの論文締切と事前申込締切の区別、Fuji Technology Pressの常時受付を確認。
- SAGEの2資料は実際のHTTP取得とPDF/DOCX本文解析に成功。意向表明日・掲載予定日を締切に採用しません。
- スキーマ検証を通して公開用データを生成。既存IDとfirst_seenを保持し、元データの行は削除しません。
- 既刊・受付状態不明のcollectionを一律openにしていたNatureの一覧処理を修正。
- 過去の誤登録5件（JSKEの会議案内・一覧リンク、IPSJの一覧見出し、Opticaの特集提案説明、VRSJの全角数字による重複）はunknownに変更して履歴を保持。

### confirmed risks

- Natureの1ページは404。Royal Societyの3件は詳細ページが403であり、締切は未確認のままです。
- 公開ページが変わると取得・抽出が失敗する可能性があります。エラーをsource_status.jsonに残し、未確認を確認済みに変えません。
- 受付状態が確認できないページはunknownです。受付終了と確認できたclosedとは区別します。
- 一部の掲載中募集には日単位の締切がありません。VRSJの「中旬」などから日を推定しません。

### unproven

- APAの個別公募ページ、ScienceDirectの一覧非掲載誌、SAGEの新規公募自動発見の網羅性。
- サイト側のアクセス制限が解消し、個別誌ページと一覧全体を継続して照合できることが必要です。

### 実行と結果

- `python -m pytest`、`node --test tests/js/test_viewer.mjs`：回帰テスト成功。GitHub上でも同じ検証を実行します。
- `python -m radar --dry-run --only sage-qjep-cultural-relativity --only sage-adaptive-behavior-neurophenomenology --only vrsj-special --only fujipress-jrm --only jske-cfp`：5取得元が成功。
- `python -m radar --check-deadlines --dry-run`：実ページの照合結果を保存。個別の404/403は上記のとおり残存。
- `python -m radar --dry-run --ingest-html apa-cfp=<公式一覧の保存HTML>`：APA48件を解析し、締切なしの記載を反映。
- `python -m radar --build-site`：生成物を検証。掲載中に締切経過済みのレコードがないことを確認。

検証は作業用コピーで順に実施しました。dry-runはSlack送信とGitHubへの書き込みを行わず、コピー内のデータを生成します。
