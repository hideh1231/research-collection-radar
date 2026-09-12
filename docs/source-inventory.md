# Source inventory

This inventory records collection coverage for psychology, HCI, neuroscience, robotics, and HRI. `config/sources.yml` is authoritative: it contains 105 sources, including 81 enabled for normal HTTP crawling. This update adds 29 enabled sources and seven disabled IEEE source definitions to the existing 69 definitions.

The 2026-09-12 local probe used the configured project User-Agent. All 81 enabled entry points returned usable pages; a one-page probe deliberately reports `pagination truncated` where further pages exist. That check establishes entry-point availability, not full pagination or availability from GitHub Actions. Newly added multi-page sources are also checked with their configured page budgets. Never interpret an incomplete page budget as a successful full crawl.

## Enabled

- Nature Portfolio: Communications Psychology, Nature Human Behaviour, Nature Mental Health, Nature Communications, Communications Biology, Scientific Reports, and submission-open Nature Neuroscience collections
- Nature Portfolio: Communications AI & Computing, plus title-filtered Communications Engineering calls
- npj: Science of Learning, Mental Health Research, Robotics, Artificial Intelligence, Digital Medicine, Digital Surgery, Biological Timing and Sleep, Dementia, Parkinson's Disease, Digital Public Health, Complexity, Sustainable Mobility and Transport
- Nature Portfolio: Humanities and Social Sciences Communications, filtered to relevant sections
- Frontiers: 19 journal listings, including Psychology, Robotics and AI, Human Neuroscience, Neuroscience, Virtual Reality, Computer Science, Digital Health, Neuroergonomics, Ethology, Ecology and Evolution, and Veterinary Science
- Springer Nature: nine BMC listings and 13 Springer Link journal collection listings
- JMIR Publications: Human Factors, Mental Health, AI, Serious Games, XR and Spatial Computing, Neurotechnology
- Taylor & Francis: `special_issues` calls from the official WordPress REST API, filtered by configured journal names and psychology, HCI, neuroscience, robotics, and HRI keywords/domain groups
- Cambridge University Press: Robotica, Personality Neuroscience, Psychological Medicine, CNS Spectrums, and BJPsych Open call-for-papers listings
- PLOS: official calls-for-papers API; Royal Society: official theme pages
- Domestic: Journal of Robotics and Mechatronics, VRSJ special issues, IPSJ CFP list, and JSKE

Existing full Nature Communications and Frontiers Computer Science listings already cover the narrower local source proposals. Existing source keys and publisher identities are retained instead of crawling those URLs twice. Nature Human Behaviour and Nature Mental Health `/collections` listings require an explicit open-submission status to avoid importing editorial-only collections.

## Collection and failure handling

- Taylor & Francis: the official `special_issues` REST API exposes journal, title, copy, and deadline. The complete local probe collected 80 matching calls across six pages. Publisher-wide calls are filtered before normalization.
- JMIR: the public journal-filtered announcements API collected 17 calls across six configured journals, including calls omitted by the first HTML page. Nine calls had an explicit date; complete detail checks without a date retain `not_listed`. Journal IDs are verified against the API response so an ignored filter cannot silently import another journal's calls.
- JMIR and Cambridge: listings identify calls; matching official detail pages supply explicit submission status and deadlines. Publication dates, bare year/month values, unrelated page dates, and invalid dates are not invented into exact deadlines. An identified open call without an explicit date is recorded as `not_listed` only after a successful detail check.
- JSKE: the repeated September Crawl failures were HTTP timeouts that escaped the collector and terminated the pipeline. Its page responded locally during this audit. The pipeline now records such failures, preserves prior records, continues other sources, and exits nonzero after saving results.
- `scripts/probe_sources.py` uses the same collector registry as the pipeline. It records per-source failures and supports `--only`, `--include-disabled`, `--max-pages`, and a JSON `--output` without changing the index or sending notifications.

## Outside the normal HTTP crawl

- APA, Elsevier ScienceDirect, APS, Science Robotics, T&F Author Services, SAGE, PNAS, PNAS Nexus, JOSA A, and watched Wiley journals use the existing weekly rendered-listing ingestion or explicitly supplied HTML snapshots. They remain disabled for the ordinary HTTP crawl. A browser challenge is recorded as a failure; it is not bypassed.
- IEEE Robotics and Automation Society Transactions: source definitions and a dedicated parser are present for T-RO, T-ASE, ToH, T-FR, T-MRB, T-RL, and T-SRO. They remain disabled because the normal HTML endpoints currently return Cloudflare HTTP 403 to the scheduled client. The public WordPress endpoint is intermittent and is not yet reliable enough to enable.
- Wiley: official call pages were found, including the BPS Psychology and Psychotherapy hub (`https://bpspsychub.onlinelibrary.wiley.com/hub/journal/20448341/call-for-papers`). The scheduled HTTP client receives a Cloudflare HTTP 403 from both this hub and the canonical Wiley Online Library endpoint, so no Wiley source is enabled.
- SAGE: the publisher-wide Open Call for Papers page (`https://journals.sagepub.com/open-call-for-papers`) and journal-specific pages such as Organization (`https://journals.sagepub.com/page/org/call-for-papers`) are official and readable in indexed/browser results, but the scheduled HTTP client receives a Cloudflare HTTP 403. No SAGE source is enabled.
- MDPI: official listing pages include the publisher-wide library (`https://www.mdpi.com/special-issues`) and journal pages such as Robotics (`https://www.mdpi.com/journal/robotics/special_issues`). A browser-like request can return the HTML listing, but the scheduled client’s custom User-Agent is denied (HTTP 403 Access Denied after an initial 200 response), so the endpoint is not stable enough to enable. The HTML shape was recorded for a future parser: `a.title-link` under a `generic-item article-item`, with deadline/status/keywords in the parent card.
- ACM: the official Digital Library call listing (`https://dl.acm.org/journal/tochi/calls-for-papers`) returns Cloudflare HTTP 403 to the scheduled client. Recheck when ACM provides a public JSON/RSS endpoint or permits the project User-Agent.
- IOP: the official Focus Collections listing (`https://iopscience.iop.org/collections?currentPage=1&nextPage=2&openForSubmissions=yes&orderBy=relevance&pageLength=10&previousPage=-1&searchDatePeriod=anytime&terms=`) redirects the scheduled client to a Radware validation page. Recheck when IOP exposes a public endpoint without a bot challenge.

The IEEE, Wiley, SAGE, MDPI, ACM, and IOP access limitations above come from the prior source audit; they were not rechecked as enabled sources in this run. The normal crawler does not require these sites to be enabled in order to collect from the supported publishers.
