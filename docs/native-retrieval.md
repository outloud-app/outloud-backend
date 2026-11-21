# Native research path

The interactive research endpoint now defaults to `OUTLOUD_RETRIEVAL_MODE=native`.
It does not silently use web-index queries when native acquisition is disabled or fails.
`indexed` remains an explicit diagnostic mode. Existing collected original posts can
still be reused after product-specific evaluation; they are not newly fetched posts.

## What gets searched

1. Read product metadata and establish the job, customer problem, audience and known competitors.
2. Search TikTok and Instagram independently for audience niche content: education,
   routines, relatable experiences and useful demonstrations. Exact app features
   are not required for creative inspiration.
3. Run separate TikTok and Instagram searches for competing software doing the
   customer job. Search intent does not prove a post belongs in Competitors.
4. Search Reddit and X for current audience difficulties, questions and unmet needs.
5. Deduplicate original records, shortlist, evaluate product fit and rank using
   available engagement evidence. Gemini interprets and evaluates; it does not
   invent posts, metrics, transcripts or thumbnails.

Four media calls and up to six conversation calls each request up to 20 originals.
Conversation planning produces three distinct activity groups per network: the
customer task, workflow friction and adjacent descriptions of the same need.
These are candidate requests, not guaranteed recommendations. Duplicate original
posts are merged before ranking. Every call remains independently budget-gated. The
quality report records per-platform/lane collection counts and failures separately
from the later shortlist and accepted-result counts.

## Existing provider adapters

| Network | Collection mechanism | Per-run cap |
| --- | --- | --- |
| TikTok | Apify `clockworks/tiktok-scraper`, video search queries | $0.50 |
| Instagram | Apify `apify/instagram-hashtag-scraper`, keyword reel search | $0.10 |
| Reddit | Apify `themineworks/reddit-scraper`, search | $0.50 |
| X | Configured existing Apify collector, search | $0.10 default / $0.01 alternative |

These are the configured maximum charges, not verified current price quotes.
Instagram keyword search is the collector's capability; it is not a promise of
the same results as an authenticated Instagram feed. Platform availability and
provider quotas still apply. No user social login cookies are exported.

The native source path is separate from `collect_public.py`, which remains a
public-index/RSS background collector. It has not been replaced by a managed
native scheduler in this change.

## Verification and cost controls

`scripts/research/native-preflight.py` reads local configuration and the budget
ledger without network calls. It prints credential presence, never credentials.
Load the private environment before running it if checking the service's settings.

The expanded collection plan has a combined maximum of $3.00 with the default X
collector ($2.73 with the Raven alternative), before product planning, evaluation
and possible media refresh costs. These are upper-bound reservations, not a new
spending authorization; the shared approved ceiling still applies. New provider
starts remain disabled in the main service configuration.
The user subsequently approved a $6 native-search comparison on 8 November 2026,
raising the authorized lifetime evaluation ceiling to $16.10. The comparison ran
on Watchers and Cal AI without a subscription or billing upgrade. Collection is
not enabled globally by that authorization.

See [the comparison review](../artifacts/native-comparison-review.md) for actual
candidate counts, selected results, original links, costs and human-review findings.
Offline tests alone do not establish live recommendation quality.

## Conversation refinement after the first comparison

The service now plans three distinct queries per network and constrains the two
broader searches by core activity words from that product's first group. Thus
"manual data entry" cannot search the entire platform independently of meal or
calorie tracking. These constraints are product-derived, not per-app rules.

The first unscoped friction-query check collected 37 originals across Watchers
and Cal AI but added no accepted conversations. That negative result exposed the
query drift; it is not reported as a recall improvement. Subsequent live checks
are recorded below; adding a scope did not by itself solve retrieval.

Evaluation policy 13 reads resolutions at the end of a story and distinguishes
workflow friction from broad outcome questions. Explicit irrelevant verdicts
with no evidence quote are now cached as exclusions for the exact product,
source and policy. They cannot qualify as displayed references. This avoids
paying repeatedly to reject the same unrelated post.

Detailed local evidence: `artifacts/conversation-refinement-2026-11-08.json`,
`artifacts/conversation-friction-search-2026-11-08.json` and
`artifacts/conversation-query-scope-check.json`. Lifetime conservative spend
reservations after these checks total $15.82, within the $16.10 authorization.
No paid scheduler or production deployment was enabled.

## Native X query comparison and quote-routing fix

The grouped Boolean keyword check returned 32 originals, many without the
required activity terms, and zero accepted conversations. The provider's raw
`searchQuery` field confirms the full query was sent; it does not prove X enforced
every clause. Do not label this a model-filtering failure alone.

Two simple native searches (`staring charts` and `calorie tracking`) then returned
40 originals with visibly better topical alignment. These are diagnostic search
terms, not hardcoded per-product production rules. X plans now compile each
activity group into an independent plain keyword query. Broader groups retain a
product-derived activity word when needed. Reddit keeps explicit Boolean groups.
Activity groups are stored separately so compiler upgrades can reuse product
understanding without a new model call. Alternate phrases are retained in that
plan; this is not an unbounded search expansion.

Four borderline posts were separately rechecked. Policy 14 distinguishes an
author's explicit ongoing process burden from an advertiser's rhetorical hook.
The local quote-routing check also needed whitespace normalization: a missing
title introduced a leading space, breaking an anchored implicit-first-person
rule. With that fix, one newly retrieved Watchers complaint qualifies. The two
Cal AI controls did not establish a qualified audience conversation. Do not
describe the 16 other automatically selected topic references as 16 leads.

Evidence: `artifacts/native-x-keyword-check-2026-11-08.json`,
`artifacts/native-x-simple-check-2026-11-08.json`, and
`artifacts/native-x-intent-review-2026-11-08.json`.
Conservative lifetime reservations are now $16.08 / $16.10; they are not invoices.
The independently bounded diagnostic checks did not enable a paid scheduler or
production deployment. Current live evidence still does not establish the full
20-conversation target for either product.

## Saved-record recovery — 9 November

Policy 14 now reuses exact-input policy 13 media and competitor verdicts because
their evaluation contract did not change. Explicit unresolved requests for help
are also reusable only with a literal source quotation, relevance of at least
0.65, and passing current routing checks on both the full post and quotation.
Ambiguous rants, advertiser hooks, changed captions and changed product briefs
do not qualify for this compatibility path. Original verdict policy/provenance
are retained; this is not a fresh evaluation.

The offline corpus audit recovers one recent Watchers Reddit request (taking
current-policy selected Conversations from one to two) and five Cal AI competitor
posts. It adds no Cal AI Conversations. These are narrow exact-comparison-context
counts, not total customer workspace coverage or newly collected leads.
Evidence: `artifacts/corpus-reuse-audit-2026-11-09.json`.

The retrieval shortlist also excludes undated or older-than-30-day help requests
before embedding/evaluation, even when those posts have engagement counts.
Historical competitor/creative references retain their separate age policy.
279 tests pass. No provider calls, increased spending or deployment occurred.
The cached-only publication worker skipped all 18 local snapshots because none
carried its required quality report; no customer results were overwritten.

## Workspace delivery repair — 9 November

The local service had restarted without `OUTLOUD_LIVE_SEARCH=1`; opening Watchers
therefore ran the legacy catalog matcher and delivered an empty workspace even
though verified originals were in the corpus. Use the persistent repository
launcher instead of an ad-hoc uvicorn restart:

```
/Users/apple/VSCodeProjects/outloud-backend/.venv/bin/python scripts/research/serve-local.py
```

This launcher explicitly enables the research path in cached-only execution,
loads private credentials outside the repository, and disables new collection.
Cached-only research bypasses planning, embeddings, evaluation and enrichment;
it reads exact-product saved verdicts and runs current quality/freshness checks.
Its workspace cache namespace is distinct from live acquisition, so it cannot
mask a later fully enabled collection session. Health reports `collected_store`
and `cached_only: true`. No budget ceiling is raised.

Browser verification: saved Watchers now shows the 3 November Reddit question
and 8 November X complaint under their respective filters. These are two audience
conversations plus one creative reference, not three conversations. Cal AI still
has no current verified conversation; this repairs delivery, not collection
coverage. Endpoint regression tests cover an empty legacy snapshot, reopening
after loss of process-local jobs, and forbidden provider calls. 280 tests pass.
