# Outloud backend

Standalone backend for the native Outloud app. The landing page remains in
`/Users/apple/VSCodeProjects/outloud-website`; the Mac app remains in
`/Users/apple/XcodeProjects/outloud`.

## Components

- `research/`: the research API, shared public-post corpus, project-scoped research snapshots, native platform adapters, relevance evaluation and background workers.
- `scripts/research/`: local service launcher, collector, diagnostics and acceptance checks.
- `licensing/`: the existing license/commerce authority, including its separate sandbox/live configurations.
- `outloud_api/`: the earlier local project/draft API; the native research client uses the service on port 8766.

## Local development

```sh
.venv/bin/python -m pytest research tests -q
.venv/bin/python scripts/research/serve-local.py
```

The launch agent `com.wirebuilds.outloud.local-research` points here. Configuration
is read from `~/.config/outloud/research.env`, never from the website. Existing
SQLite databases moved intact into `research/.data/`. Nothing was deployed.

The launcher defaults to cached results. `OUTLOUD_LOCAL_LIVE_NATIVE=1` explicitly
enables native collection in the local development service. Every paid operation
still reserves its maximum against the durable provider budget; failed/uncertain
attempts keep their reservation. It never upgrades a provider plan or retries an
unavailable source through web-index search.

## Data ownership and reuse

Public originals are stored once by canonical platform URL, with retrieved text,
media references, publication dates and observed metrics. A full-text index finds
relevant older niches even when newer unrelated posts fill the corpus.

Product profiles, relevance decisions and published workspace snapshots remain
scoped to their inputs/owner. Public corpus records explicitly exclude customer
notes, project IDs, owners and product-specific verdicts. Two projects can reuse
the same post and search response, but never inherit each other's relevance
verdict merely because their categories match.

Native search results are reused for six hours while collection is enabled;
completed empty searches retry after fifteen minutes. Running jobs retain their
identity and concurrent requests share one paid start. Paused collection can
read old cached records without paying. New content is ranked again for the
current product and still passes publication-age and evidence checks.

## Feed rules

- **For You / Home discovery:** broader niche education, useful demonstrations,
  routines and relatable content. Product context and required keywords guide
  exploration; exact feature clones are not required.
- **Competitors:** an identified competing product plus evidence that its own
  business/maker published the post. Third-party reviews do not qualify.
- **Conversations:** current Reddit/X unmet needs or requests relevant to a
  capability the product actually offers. Broader audience overlap is not
  sufficient evidence of a buying lead.

Default background collection uses native TikTok/Instagram/Reddit/X adapters.
Old injected web-index adapters remain only in diagnostic tests, not the normal
service or background collector. Collected counts are candidates, not proof of
usefulness. Tests do not establish live coverage; see acceptance artifacts.

## Following and coverage

The desktop brief carries project-specific `followed_sources` separately from
required keywords and competitors. Adding/removing a source invalidates that
project's snapshot identity and refreshes research. Topic preferences feed native
media plans and scheduled conversation searches on their selected network.
Account preferences prioritize matching originals already in the corpus; direct
continuous account monitoring is not implemented. Following never grants
competitor ownership or bypasses relevance, evidence, or freshness checks.

Watchlist changes reuse the original product understanding and factual source
verdicts when the actual product brief and source text are unchanged. They do not
reuse another product's verdict. Preferences remain outside public corpus records.
Following lists show matching posts from the project's accepted references.

Cached refresh diagnostics separate candidate counts, evaluated counts, accepted
counts, and missing collection from pending review. A `has_matches` status is not
launch readiness. `scripts/research/review-cached-samples.py` reports these for
three distinct product profiles with network requests disabled. Complete checked
feeds are served before credential preflight or paid planning, including when a
collector is temporarily unavailable.

## Current evaluation authorization

On 20 November the user approved **up to US$10 additional native-search testing**,
starting from US$16.08 in conservative reservations. The absolute lifetime
ceiling was initially US$26.08 and is now US$36.08 after the second approved extension. This is provider testing cost, independent of the
product's £99.99 price. The ledger is preserved across folder moves and restarts.

An old background collector was stopped during migration. Any files it recreated
at the previous location were preserved under `migration-recovery/`, outside the
website, rather than discarded. No old web-index watcher remains running.

Credential access can be checked without starting paid work:
` .venv/bin/python scripts/research/native-preflight.py --verify-access`.

The replacement local Apify token uses restricted execution, Actor read/run/list
permissions, access to its run storages, and permission to create its own storage
resources (the TikTok collector requires a separate request queue). It does not
grant storage-wide deletion or account administration. It expires 19 February
2027. Its value remains only in the private configuration file.

## Native loading and feed publication

The authenticated desktop `/desktop/projects/{id}/stream` endpoints now deliver
checked partial results with revision numbers. Entitlement/owner checks apply to
every poll. Browser endpoints keep their limited projection; a query parameter
cannot request the full desktop feed. Native refreshes preserve visible cards
until the complete snapshot arrives.

Quality policy 19 keeps relevant third-party product demonstrations in For You,
while Competitors requires a maker quote or matching native account plus literal
brand voice. A failure to prove account ownership is not by itself a reason to
reject an otherwise useful third-party demonstration. Relevance, dates and real
engagement checks still apply.

Offline evidence is in `artifacts/cached-feed-review-2026-11-20.json`. These are
checked samples, not a claim of sufficient fresh conversation coverage or launch
readiness. The local launcher remains in cached mode under the approved provider
testing ceiling.


Core-feed verification on 20 November now includes native Instagram/TikTok media
and Reddit/X originals across three different product jobs. See
`artifacts/core-feed-reviewed-2026-11-20.json` for the manually inspected run.
For You excludes text posts and weak cross-niche inspiration. Conversation
verdicts explicitly distinguish software/workflow needs from general outcome
advice. Sparse conversation lanes receive one additional, different native query
per deficient platform, within the same durable spend ceiling. No web-index
fallback is used. Local current adapters are Raven for X and Harsh Maur for
Reddit; the previous X adapter had exhausted its trial quota, and the previous
Reddit path often returned archival/search-backed records.

The user approved another US$10 on 20 November, extending the hard cap from
US$26.08 to US$36.08. Reservations remain conservative maxima, not confirmed bills.

Preview delivery is verified separately from collection counts. Expired Instagram
cover URLs can refresh through the authenticated, owner-scoped desktop thumbnail
endpoint using the original public post. TikTok playback uses its official embed
player, avoiding dependence on expired signed video/cover links. Instagram video
references use the public post embed. No autoplay is requested. Public preview
refreshes do not start paid collectors. Platform removals or access restrictions
remain possible; the original source link remains available.
