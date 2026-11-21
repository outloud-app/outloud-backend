# Research pipeline audit — 7 November 2026

The implementation is product-driven, but live data coverage is not ready to promise consistently useful results across arbitrary niches.

| Requirement | Current implementation | Remaining limitation |
| --- | --- | --- |
| Collect first | Public source store; bounded local collector rotates registered niches across Reddit, X, Instagram and TikTok; new research streams checked partial snapshots | This is an opt-in local process, not a deployed multi-platform ingestion service. Index failures and the shared daily request cap limit collection. |
| Model once | Cached product-specific plan: 15–20 audience phrases (requests 18), six creative and six competitor phrases, suggested subreddits and adjacent topics | Suggestions must be verified. Short valid phrases are accepted rather than discarding an entire plan. |
| Rank in stages | Up to 300 corpus candidates; date/duplicate/promotion routing; cached embeddings; at most 50 candidates evaluated in independent batches | Embedding failures use lexical ranking. Sources provide up to 8,000 characters of available text, sometimes only an index excerpt—not guaranteed full original posts. |
| Label matches | Direct, Adjacent and Related verdicts with verbatim source evidence; dates and recorded counts when available | Labels do not rescue irrelevant material, stale conversations or invented performance. |
| Relative engagement | Same-community/creator, similar-age median requires ten peers. Growth comparisons require two real observations and five comparable peers | With insufficient baseline, retrieved counts are labelled measured, not outperforming. No flat 10,000-view admission rule. |
| Competitors | Optional field accepts three names or public links, visible in its own disclosure; used in search and semantic context | A known product name does not guarantee an indexed official social account. Account resolution and verified media collection remain important. |

Generic policies distinguish creative inspiration, same-job competitor offerings and current unresolved audience needs. There are no Watchers-specific query templates. Regression fixtures cover meal planning, exam revision, invoicing, accessibility and pet medication. Fixture verdicts test routing and cache isolation; they are not evidence of real-world relevance.

Live samples in `artifacts/multiniche-live-retrieval-audit.json` returned:

- Meal planning: 5 collected candidates, 0 accepted.
- Invoicing: 10 collected candidates, 1 accepted.
- Exam revision: 11 collected candidates, 3 accepted.

These were deliberately bounded single-query-per-network samples, not exhaustive collection. X returned no usable candidates. Some public search calls failed. Relevant creative posts lacked retrieved engagement and were excluded rather than described as popular. No additional Apify runs were started during these samples.

Providers: Exa's keyless MCP search for indexed public source discovery; Gemini for planning, embeddings and source-specific semantic decisions; Apify adapters for separately authorized native media/metrics collection. Google chat login is not used as an API. New Apify media runs remain disabled in the local service.

## Authorized cross-niche media check

Completed the approved Instagram/TikTok check with a combined $0.60 maximum run cap, using included credits without a billing upgrade. This cap is not a statement of the final provider charge. Evidence: `artifacts/multiniche-media-check.json`.

Six original post URLs were checked across meal planning, invoicing and exam revision. Five returned original thumbnails and measured engagement. Native publication dates showed those five were from 2023–2024, despite the search candidates appearing more recent. They fail the existing 365-day discovery window. The sixth invoicing post returned no verified engagement. Zero of these six candidates passed final selection; no current conversations were established by this media-only check.

The check exposed and fixed a missing-date crash in cohort comparison. Builder routing now distinguishes software offerings from unrelated client work; generic builder wording cannot override a semantic verdict into the competitor lane. Rechecking reused persisted provider runs and cached semantic verdicts; it did not start new media runs.

The adapters can retrieve real media and metrics. Fresh source acquisition remains the blocker: this check does not establish launch readiness or useful coverage across niches.

## Public preview

Show three matches per lane, prioritizing one per available platform; four may be shown when four platforms have qualifying results. Locked teasers contain bounded actual public source titles, excerpts and available images, rendered inert and blurred. No made-up avatar placeholders. Teasers intentionally contain public snippets: cosmetic blur is not security or license enforcement. Full analysis, original links and player URLs are excluded from locked teaser records. Desktop entitlement checks remain separate.

Missing platforms and absent recent audience requests are unresolved coverage gaps, not results to invent. Do not publish this as a reliable cross-niche discovery experience until real provider checks meet the product-quality bar.


## Fresh acquisition and feed spacing — 7 November

Discover uses a compact masonry arrangement for mixed-height media and text cards. Browser layout checks confirm consistent 18px desktop and 14px phone gaps in both For You and Competitors, with no horizontal overflow. Layout verification uses local fixtures, not fabricated research results.

The acquisition plan now substitutes up to three public Reddit community feeds for existing search slots, keeping the existing 24-request ceiling. Original Atom publication dates, author text and links enter the shared corpus before product-specific semantic evaluation. Updated/edit dates cannot make an older post current. Community feeds are cached for 15 minutes and respect shared persisted backoff after 403/429. They provide no invented vote counts. Search acquisition now requests a recent 90-day window for social creative candidates and 30 days for audience discussions; search hints alone are not verification.

Original platform publication dates and captions are now protected from later search-index overwrites. This prevents a newly indexed timestamp from making an old native post appear fresh. Audience conversations still require a current unresolved need; promotions do not count as leads. The planner now prefers discussion-oriented communities over photo showcases.

The first bounded native-feed audit collected 22 recent meal-planning posts. One same-job competitor passed; no current audience request passed among the eight evaluated candidates. Subsequent communities were rate-limited and were not retried in that run. See `artifacts/fresh-community-audit.json`; fresh-feed availability remains variable, and this does not establish universal launch readiness.

A follow-up checked a discussion-oriented cooking community: 24 recent original posts were collected, but none of the eight evaluated candidates passed for PantryMate. The remaining checks respected the provider's shared backoff. This confirms fresh ingestion works without claiming that every recent community post is a useful audience lead. Evidence: `artifacts/fresh-community-followup.json`.


## 7 November: product understanding and queue repair

Internal research now reads the fuller stored publisher metadata, while preserving the visitor's original brief. One grounded job/problem/audience model feeds embeddings and evaluation; each inferred field requires a verbatim source excerpt. Explicit visitor problem/audience fields take priority. Query planning uses Gemini's structured JSON schema with bounded phrase counts. A failed plan produces a retryable service error rather than silently switching to broad category queries.

Competitor decisions now require an identifiable product and a quoted capability. The target product itself cannot become its own competitor. Product identity is included in verdict cache keys. Planning/evaluation cache policies were advanced to invalidate earlier broad decisions.

Independent research keys use separate, reference-counted locks; repeated requests for the same key still share the work. Search futures are collected as they finish instead of waiting in submission order. No new background paid media collection has been enabled.

Validation: isolated automated tests exercise metadata preservation, unsupported inferences, explicit-field precedence, concurrent research, and own-product competitor rejection. These are contract tests, not proof of live result quality. Live Gemini planning checks encountered HTTP 503, HTTP 404 for the older 2.5 model, a timeout for 3.1, and an incomplete response from 3.5 before adding schema constraints. Full cross-niche live quality acceptance remains required before publication.


Live follow-up: grounded Cal AI understanding succeeded. The old two cooking questions and the target-product founder success story were rejected; Hit Cal remained an evidenced competitor. Saved proof: artifacts/cal-ai-grounded-context-audit.json. Fresh search collected 266 candidates, shortlisted 50, and returned 10 competitor sources and 4 discussions, but ZERO measured For You posts. The discussion audit still found overly broad weight-loss topics; policy 10 tightens the customer-job requirement, and has NOT yet passed a new live cross-niche acceptance test. One evaluation batch returned malformed JSON; schema constraints were added to evaluation as well as planning. Saved fresh proof: artifacts/cal-ai-fresh-research-audit.json. The pipeline is NOT launch-ready.

Quota repair: provider-backed searches now consume one daily slot immediately before each actual retrieval attempt, rather than reserving 24 slots before planning. Same-source metadata and measured engagement remain reusable. Reserved provider budget after these checks: $4.41 of $5 (reservations include failed/uncertain calls, not a final provider invoice). New paid Apify runs remain disabled. Local service restarted with the changes.

## Native conversations and workspace verification — 7 November follow-up

Added separately gated native conversation adapters for `atomus/twitter-scraper` and `themineworks/reddit-scraper` through the existing Apify account. Queries derive from the cached grounded product job. Native search requests are bounded to 20 posts and 90 seconds; maximum run charges are $0.10 for X and $0.50 for Reddit. Pending/completed run IDs are persisted so refreshes reuse collection. New collection remains disabled in the local service. Neither adapter exports browser login cookies.

The initial $0.10 Reddit request was rejected before collection because the actor requires a $0.50 minimum cap. A subsequent $0.50 bounded check completed. X returned ten original posts with dates and counts; Reddit returned twenty records, fourteen with sufficient original body text for evaluation. These are acquisition counts, not accepted leads. Unknown vote counts remain absent.

Actual X evaluation found three current calorie-tracking complaints, including difficulty logging food and barcode scanning behind a paywall. The Reddit check also exposed a broad-audience false positive: a medication-switching question mentioned calorie tracking but requested help with a different task. Quality policy 11 rejects Related-only conversation matches; Direct/Adjacent requests still require exact unresolved-need evidence and verified original dates within 30 days.

The finished saved Cal AI workspace now contains both X and Reddit in its visible conversation selection. Browser verification used the actual saved project and API results, not fabricated result fixtures. Reopening completed in about one second; inline skeletons, loaded thumbnails, no feed iframe players, immediate ending dialog, no JavaScript errors and no phone-width overflow were verified. Evidence: `artifacts/cal-ai-service-stream-audit.json`, `artifacts/cal-ai-native-x-evaluated.json`, `artifacts/cal-ai-native-reddit-evaluated.json` and the `cal-ai-real-workspace-*.png` screenshots.

Validation: 187 backend tests pass. Conservative reserved evaluation budget is $7.65 of the authorized $10, including failed or uncertain reservations. This is not an invoice total. Instagram attention quality and consistent cross-niche coverage still fail public release acceptance. Nothing was published.

## Keyword media and final local checks

Instagram's separate hashtag actor now supports `keywordSearch` with multiword activity phrases and reel results. A $0.10-capped native keyword audit retrieved eleven usable original posts, including a calorie-tracking educational reel with 59,519 retrieved plays and a competitor reel with 20,730 plays. A 41-million-play cooking post was category overlap, not sufficient evidence of relevance. Evaluation policy 11 now explicitly distinguishes supported customer activities from incidental industry overlap. Conversation admission also checks that the quoted need itself expresses an unresolved request/frustration, rather than simply accepting the model's unresolved label.

The generic adapter supports both native X and Reddit searches with separate cap enforcement and persisted jobs. Cached observation timestamps remain unchanged; refreshing cached results cannot manufacture a new engagement observation. Original Reddit title and body remain separate, with native permalink precedence.

Final checks: 189 backend tests pass, TypeScript passes, and browser checks using the saved Cal AI project pass for inline skeletons, actual image loads, no feed iframe players, no JavaScript errors, immediate ending dialog, and no phone overflow. The latest policy refresh completed in 36 seconds; reopening used the completed cache immediately. These are local measurements, not an SLA.

Cross-niche policy checks reused collected real data without starting new media runs: InvoiceTrail returned eight creative references and three competitor sources; RecallRoom returned eight creative references and three competitor sources. Neither media-only sample established current audience conversations or Instagram coverage. Both fail release acceptance. Cal AI also still lacks a reliable comparative engagement baseline. Evidence: `artifacts/cal-ai-native-quality-followup.json`, `artifacts/cal-ai-instagram-keyword-audit.json`, `artifacts/invoicetrail-policy11-audit.json`, `artifacts/recallroom-policy11-audit.json`.

Conservative reserved evaluation budget: $8.17 of $10. New native collection remains off in the local service, and nothing has been deployed.

## 8 November: cross-product queries and provider failure diagnosis

Native conversation planning now produces two or three plain activity phrases. The adapter quotes each phrase and controls the Boolean operators itself; multiword phrases can no longer turn into a broad bag-of-words search. Query cache policy 2 invalidates older ungrouped queries. Natural requests such as “What's your normal process when an invoice goes overdue?” are recognized. Near-identical long cross-posts by the same author on the same platform collapse to one reference; independent authors remain separate.

The native X actor returned an error dataset, not an empty search: `free_tier_limit`, with a monthly free allowance of ten scraped posts. Original datasets are retained privately in the provider cache. The adapter now reports a sanitized provider-unavailable error, blocks additional native X runs and planning spend until the monthly reset, and keeps Reddit planning independent. This does not remove previously verified X posts from the shared store. It does not upgrade billing or claim X coverage is restored.

Real checks: InvoiceTrail recovered one direct unpaid-invoice conversation and five distinct competitor references from collected data. The original RecallRoom native search supplied no accepted conversations. A separate original Reddit feed check collected 24 recent GetStudying posts; 19 received verdicts and four passed the current conversation gates, including a memory-recall study-system request. Five candidates had no usable verdict and were not admitted. These are policy acceptance results, not proof that every accepted result is equally valuable or that public release acceptance passes. Evidence: `artifacts/cross-product-quality12-audit.json`, `artifacts/study-fresh-feed-followup.json`, and `artifacts/study-fresh-feed-evaluated.json`. Earlier query-policy audit artifacts contain zero usable X records; those zeros reflect the subsequently diagnosed provider quota failure, not evidence of absent audience demand.

Quality policy 12 / search version 26 invalidate older result snapshots. Validation: 194 backend tests pass. Both the local frontend `/try/` and API `/health` respond successfully. No frontend styling changed in this pass. The local research service was restarted with new paid native/media collection disabled.

Conservative reserved evaluation spend is now $9.97 of the authorized $10, including failed or uncertain calls. No more paid evaluation should be started without sufficient remaining allowance. The remaining release blockers are reliable X access, consistent Instagram/TikTok coverage across products, and comparative engagement evidence. The demo is not certified launch-ready, and nothing was deployed.


## 8 November: approved alternative X collection check

The user approved a further $0.10 for one 20-post X check and its relevance evaluation, raising the hard evaluation ceiling to $10.10. Added an explicit alternative adapter for `pro100chok/x-twitter-all-in-one-scraper` on the existing Apify account. It uses one search target, at most 20 posts, latest results, a 30-day start date, English, and no reposts. Contact-email and profile-about enrichment are disabled. Each run reserves $0.01 before starting and sends that same maximum charge to Apify. Collector-specific cache namespaces isolate the old actor's monthly quota failure. No new account, subscription, or billing upgrade was created.

One real broad invoice search returned 20 original X posts, with original publication dates and retrieved counts. Fifteen received usable semantic verdicts; five without verdicts were excluded. Eight passed current routing: six competitor references and two creative references, but ZERO audience conversations. The three model-proposed audience leads lacked an evidenced unresolved request under the deterministic gate and were rejected. The creative references do not establish outperforming content. This proves the alternative can collect X records, not that broad keyword searches produce good leads or that release acceptance passes. Saved evidence: `artifacts/x-alternative-bounded-check-approved.json` and `artifacts/x-alternative-approved-evaluation.json`. No repeat collection or evaluation was started.

Incomplete semantic batches now explicitly report missing source IDs instead of silently omitting them. Relative engagement baselines now support retrieved Instagram plays without mixing them with views. Conservative reserved spend is $10.06 of the $10.10 ceiling; these are reservations, including failed/uncertain calls, not an invoice. The ordinary local service retains the previous $10 spending ceiling and has all new paid collection disabled, so it cannot consume the remaining audit-only extension.

Validation: 199 backend tests pass. The hard-cap test verifies both caller ceilings and the absolute $10.10 ceiling. X input and normalization tests cover caps, original dates, count types, enrichment exclusions, and independent collector quota state. Public launch remains blocked by useful fresh audience coverage and consistent checked media/engagement across products. Nothing was deployed.
