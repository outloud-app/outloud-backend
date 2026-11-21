# Product research readiness — 8 November 2026

Local implementation and offline measurements only. This is not a launch approval.
Historical provider runs and earlier measurements remain in research-pipeline-audit.md and artifacts.

## Four service goals

| Goal | Current evidence | Remaining work |
| --- | --- | --- |
| Useful audience conversations checked daily | Durable daily Reddit/X collection jobs, bounded attempts, leases, failure reporting and delayed retries are implemented and tested. | Collector is not running as a managed service. A durable evaluation queue and cached publication step now connect collection to workspace updates, but paid evaluation is disabled. No sustained daily useful-result delivery has been demonstrated. |
| Fresh creative and competitor research several times weekly | Separate For You and Competitors plans rotate within three-day windows, subject to worker availability and quotas. Product-specific planning and shared source reuse exist. | Indexed discovery does not replace native media/metric collection. Broader candidate recall, known competitor accounts, engagement baselines and cross-niche acceptance remain blockers. |
| Saved results, working sources and engagement evidence | Original sources, provenance, metrics observations and product-bound evaluations are persisted. | Offline counts do not verify current link/playback availability. Add recurring source checks, unavailable-state handling and metric refresh before making reliability claims. |
| Customers return each week because it saves time | Local funnel events exist. | No customer retention or time-saved evidence yet. Measure qualified result opens/saves, source visits, new useful results per week and returning customers in a real pilot. |

## Latest saved-result audit

`artifacts/product-service-readiness.json` is generated without provider calls by:

    /Users/apple/VSCodeProjects/outloud-backend/.venv/bin/python scripts/research/readiness.py

| Product | For You / target 25 | Competitors / target 15 | Conversations / target 20 |
| --- | --- | --- | --- |
| Cal AI | 4 | 9 | 2 |
| Watchers | 3 | 11 | 1 |

These are matches passing current semantic gates, not human-approved useful results or independently verified popular content. Both products fail the proposed target volumes. The selector now supports 25 For You, 15 Competitors and 20 Conversations independently (60 total). These historical snapshots still have the low counts above. Capacity is fixed; retrieval quality and live coverage are not yet proven.

The corpus has 722 stored original source records across Reddit, X, Instagram and TikTok. Raw corpus size is not product coverage. Seven stored product subscriptions produced 56 per-lane/network scheduled checks; all await their first scheduler-run success. No recurring collector was enabled by this audit.

## Implemented in this pass

- Daily Conversations checks and three-day For You/Competitors checks with durable per-product/network state.
- Atomic worker leases, successful-check timestamps, separate errors, bounded delayed retry and cursor preservation after failure.
- Global public-search allowance enforcement immediately before each attempt; one tick permits at most four attempts.
- Preservation of longer internal metadata context while validating stored project fields.
- A read-only scorecard exposing coverage shortfalls, collection health and selection capacity against the proposed targets.
- Network-free incremental refresh reuses decisions tied to the exact product and source text. Unevaluated corpus candidates cannot become recommendations.
- Reopening a currently cached workspace includes newly evaluated corpus matches without another search. A bounded worker step can also publish these updates to saved projects.
- Fresh-feed expiry retains original references in owner-scoped server history. That history is not yet wired into the client's Saved view, which still stores IDs locally.
- Concurrent project edits are protected by compare-and-swap on worker publication; cached-only refresh preserves original search age and existing provider failure warnings.
- 253 backend tests pass, including offline fixtures spanning eight product categories. Tests verify behavior; they do not establish live result quality.

The collector uses public-index/RSS retrieval only. It does not launch native paid collection or run semantic evaluations. A completed tick queues unevaluated originals and attempts cached-decision workspace publication. `--status` / `--dry-run` inspect state; `--refresh-cached` performs only network-free publication; `--watch` explicitly starts the bounded scheduler. The separate evaluation tick is opt-in and still requires provider authorization and an available budget reservation. A managed production worker, live quality validation, monitoring and sustained end-to-end delivery are still required.

The local cached refresh published two existing real-research workspaces with zero provider calls. Cal AI now has nine competitor matches instead of eight; some individual sources changed. Those measurements predate the independent lane capacities. Watchers' lane totals remain unchanged. Dry-run evidence is in `artifacts/incremental-refresh-dry-run.json`. This is an integration improvement, not proof of improved candidate discovery.

## Retrieval corrections in this pass

- Independent audience/topic, competing-product and unmet-need embedding queries. The bounded semantic shortlist now accepts up to 90 candidates, rather than 50.
- Centralized evaluation instructions distinguish creative inspiration from current audience needs. Broader niche media no longer needs to mention the exact app feature. Cached candidate revalidation preserves this distinction; it does not approve unevaluated sources.
- Indexed creative/competitor searches allow the past year. Conversations use a 30-day window and prioritize the past week. Native Instagram collection still uses a narrower 90-day window; this pass did not run or expand paid collection.
- Collection scheduling divides each lane cadence across its query plan. Previously one phrase ran per cadence, so 18 conversation phrases could take 18 days to rotate. The new rotation remains bounded by global request quotas and requires a running worker.
- New evaluation cache version prevents reusing old rubric decisions for new evaluations. Historical saved verdicts are not presented as newly evaluated results.

## Incremental evaluation worker

- Added a durable per-product/source/policy queue. Untrusted input verdicts are stripped, canonical originals are deduplicated, and cached acceptances and rejections are reused.
- Up to four sources from one product are claimed per evaluation tick, with atomic leases, crash recovery and delayed retries for missing decisions. A late worker cannot overwrite a reclaimed lease.
- The local collector now queues candidates after acquisition. `--queue-evaluations` only prepares the inbox; `--evaluate-once` invokes the separate worker only when `OUTLOUD_EVALUATION_WORKER_ALLOWED=1`. Provider authorization and the lifetime spending ledger remain independent requirements. `--watch` does not turn paid evaluation on.
- The candidate balancer no longer stops at six sources per platform. Queue preparation accepts up to 90 balanced candidates per product and skips already evaluated originals. Legacy subscription aliases are scanned once per product.
- Offline integration tests cover new source → queue → cached decision → saved workspace, plus rejection, partial failure, policy/text invalidation, disabled execution and budget exhaustion. These tests use fixtures and mocked evaluation responses; they are not evidence of live relevance.
- Prepared 630 local evaluation jobs from the existing corpus with zero provider calls. They are candidates awaiting evaluation, not 630 useful recommendations.

## Next acceptance sequence

1. Benchmark at least eight distinct product niches against a human-reviewed live sample, separating audience problems, creative inspiration and actual competitor output.
2. Exercise the connected collection/evaluation/publication pipeline with authorized live data and a managed worker; verify useful new results, deduplication and retained saved references.
3. Verify source availability and engagement observations; do not invent missing metrics, transcripts or frames.
4. Test the full refresh loop over multiple days, including provider failure, rate limits, empty returns and recovery.
5. Run a small paying-customer pilot and measure useful discoveries and weekly returns before promising fixed result volumes.

## Cost and publication controls

The approved lifetime evaluation ceiling is $10.10. Conservative reservations total $10.06; these are not actual provider invoices. The last $0.10 extension was for one bounded X check and its evaluation, now complete. This pass made no new provider calls. New paid starts remain disabled in the main local service. Do not treat the remaining reservation headroom as permission for additional runs.

No deployment, pricing change, landing-page redesign or Mac UI change was performed.
