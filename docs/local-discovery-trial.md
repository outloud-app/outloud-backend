# Outloud discovery trial — local evaluation

Nothing in this change deploys the website or touches Stripe, licenses, the Mac app or the existing Cloudflare services. The original hero and walkthrough remain intact. `TrialEntry` adds a local-only invitation immediately after the walkthrough. `/try/` is also restricted to localhost in the interface.

## Run locally

From `/Users/apple/VSCodeProjects/outloud-website`:

```sh
PATH=/Users/apple/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH ./node_modules/.bin/next dev --hostname 127.0.0.1 --port 4321
```

From `/Users/apple/VSCodeProjects/outloud-backend/research`, in another terminal:

```sh
OUTLOUD_LOCAL_TESTING=1 /Users/apple/VSCodeProjects/outloud-backend/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8766
```

Open `http://127.0.0.1:4321/` for the unchanged hero plus trial invitation, or `http://127.0.0.1:4321/try/` for the welcome screen. Use the same hostname throughout; `localhost` and `127.0.0.1` have different browser cookies.

The API uses the existing backend Python environment. Its dependencies are declared in `trial-api/requirements.txt` for a future standalone environment. No new paid services or API keys are needed.

## Working flow

- Welcome: create a project, explore community projects, or reopen a project from this browser.
- Setup: name, platform, launch status, brief and optional category override. Launched projects can add a public link. Unlaunched projects have a collapsed optional landing-page field.
- A short animated workspace transition respects reduced-motion preferences. It does not pretend to generate content or display invented progress percentages.
- Discover: For you, possible competitors, saved references and platform filtering.
- Conversations: question/help-seeking discussions with reading, opening originals and saving. No generated replies or automated posting.
- Finish: a private rating/review, then a separate optional sharing flow.
- Publication requires explicit consent and a reviewable public card. It stores only the chosen name, public description, platform, launch status, link and optional preview image. Neither the private research brief nor feedback appears in gallery responses.
- A public page's Open Graph cover is used when accessible; otherwise the card has an original monogram cover. Prelaunch projects need no URL. Source account cards are explicitly labelled as account references, not individual posts or videos.
- The owner can unpublish from the same browser. The landing gallery renders only when one or more projects are actually published. It refreshes every 15 seconds.

## Actual research implementation and boundaries

Research currently performs deterministic keyword/category matching against `trial-api/catalog.json`. It makes **no paid model calls, search-provider calls or platform-scraping requests**. The initial catalog contains 26 real public reference links across five categories, with account references, editorial articles and discussion links. Titles and short descriptions are editorial summaries, not fabricated platform screenshots, post quotations, engagement counts or claims that a source converts. Source availability can change.

The brief can infer a category using keyword matching. The user can override it. There is no semantic competitor verification or live trend ranking. A related product is only a possible competitor. Unsupported topics and filters return an honest empty state rather than unrelated filler.

Each project receives at most six Discover references plus four Conversations. Reopening, changing filters and saving reuse the same stored result set. Identical repeat submissions reuse the project. Local evaluation caps are three distinct projects per browser per UTC day, twelve per client IP per day and thirty globally per day. These counters are reserved in a SQLite transaction and roll back when a request is rejected. Every request's existing session/project ownership is checked.

Metadata fetching occurs only when the owner previews a public card with a URL, capped at five per browser/day. It is HTTPS-only, bounded in size/time/redirects, pins connections to a validated public IP and rejects private-network addresses. A failed metadata fetch uses the monogram cover.

SQLite data is in ignored `trial-api/.data/trial.sqlite3`, independent of real commerce and licensing data. Review data persists there; saved references persist in this browser's local storage. The owner session is an HTTP-only, same-site cookie lasting seven days. This is local evaluation identity, not a cross-device account or production authentication system.

## Before a separately authorised publication

Keep the research limitation visible. Decide whether to expand the curated catalog or attach a separately budgeted search provider; do not promise native cross-platform live feeds. Deploy the FastAPI service with persistent storage and HTTPS, update allowed origins, use secure cookies, introduce public abuse protection and moderation/removal workflows, and update trial privacy disclosures. Add a proper ownership recovery mechanism before relying on browser-only session recovery publicly. Remove the localhost feature gates only as part of that release. No public deployment has been attempted here.

## Verification

API tests: consent enforcement, private/public separation, ownership isolation, result caps, idempotency, quota rollback, topic matching, unsupported topics, invalid/private URLs, origin checks and private-address rejection for previews.

Browser checks: complete desktop flow including publication/unpublication, empty landing gallery, saved-reference persistence, equal action button radii, mobile layout without a sidebar or horizontal overflow, readable errors and working platform filters.

The original home page is backed up in `artifacts/trial-backup/page.tsx.original`. Browser screenshots and the repeatable interaction check are in `artifacts/trial-*.png` and `artifacts/check-trial.cjs`.

## Setup revision: public-link import

The brief form follows the approved compact reference: an underlined name/link, inline platform/status menus, and matched action radii. Menus support keyboard navigation, Escape, outside dismissal, checked options and reduced motion. The glass treatment is a web style, not a native macOS menu.

Launched projects require a public link. Read my app calls `/metadata`, which extracts the page's published Open Graph/description metadata into a reviewable brief. It does not use an LLM or generate unsupported claims. The description textarea is hidden unless the visitor explicitly edits the imported brief or chooses manual fallback after a blocked/insufficient page. Unlaunched projects retain their description field.

Metadata imports reuse the bounded, DNS-pinned HTTPS fetcher. Results cache for six hours, with eight attempts per browser/day and forty fresh imports globally/day. Failed imports also consume the attempt allowance. No billing connection or model credentials have been added. Public sites that require login, JavaScript rendering or block automated access may need another public link or manual details.

## Directory and review revision

- Trial invitation: “Try a limited / discovery demo.” Existing hero unchanged.
- Finish exploring is visible in a sticky workspace header. A pre-order link leads to the existing pricing section, with copy explicitly referring to the planned Mac app and separate AI credits.
- Source cards are shorter and do not stretch to fill their grid row.
- Community projects use a compact icon-first directory with search and platform filters, not tall cover posters. Apple store links use the official iTunes ID lookup for artwork; Google Play uses the listing image; websites use an apple-touch-icon or favicon. Owners can supply an optional public icon URL. No arbitrary image uploads or new paid services were introduced. Existing public local project icons were refreshed from their already-published links.
- 39 shared category choices, including automatic matching and Other, are drawn from Apple and Google's official main-category lists with trial-specific additions. Category choice does not manufacture source coverage for unsupported niches.
- NEW reviews are public. The form states this before Post review, offers an optional display name, and never publishes the private project brief. The public reviews endpoint/section returns actual submitted ratings and an average; no invented reviews or sample social proof is seeded. Rating of Outloud is separate from the quality of a listed app. Owners can remove their review from this browser.
- Old reviews submitted under the earlier private wording remain private unless the owner resubmits using the public form. This preserves the earlier privacy promise.

Category references: https://developer.apple.com/app-store/categories/ and https://support.google.com/googleplay/android-developer/answer/9859673
Directory reference: https://linear.app/customers
Apple software lookup reference: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/LookupExamples.html

## Developer testing / URL and dialog fixes

Set `OUTLOUD_LOCAL_TESTING=1` for local evaluation. This permits six distinct research projects per browser/day, with larger local IP/global headroom and metadata/preview allowances. Without this environment flag, existing standard limits stay unchanged. Local counters were reset on 2 November without deleting projects, reviews or public cards. Browser tests for the dialog/link behaviour use intercepted fixture requests and consume no research quota.

Public links accept bare domains or www domains and are normalized to HTTPS in both UI and API. An entered http URL is upgraded; unrelated schemes and private-network URLs remain rejected. Review dialogs explicitly use fixed inset positioning and auto margins to stay centered after CSS resets, with a translucent neutral glass surface and scrollable height bounds on phones.

### Review, sharing and homepage scale

The primary finish action now posts the public review before opening the optional project-sharing form. Review failures preserve the draft and do not advance; sharing still requires an explicit consent checkbox and a public-card preview. A secondary action posts only the review. The centered web dialog uses translucent layers, backdrop blur and bright edge highlights, with a solid fallback when transparency is unsupported or reduced. This is a browser material, not a native macOS Liquid Glass API.

The landing page displays at most six public projects and links to the complete directory with its actual count. The directory retrieves 24 per page, with Load more for subsequent projects. The backend no longer silently stops at the first 24. `/gallery/count` counts only published projects; `/gallery?limit=6` and `/gallery?offset=24` retain the existing array response. There is no separate total-publication cap; new projects remain subject to research quotas (six per browser/day in the local developer mode). Existing publications are preserved.

Browser-only fixtures in `artifacts/check-trial-review-gallery.cjs` demonstrate 25 published projects without inserting examples into the database. Desktop and mobile screenshots are `artifacts/landing-25-projects-desktop.png` and `artifacts/landing-25-projects-phone.png`. This check also verifies successful save-before-share, draft retention after a failed review request, explicit preview, mobile fit and directory pagination. Nothing has been deployed.

### Review carousel and private contact field

Public reviews now rotate one at a time only while at least 35% of the section is in view. Rotation pauses on hover, keyboard focus, a hidden browser tab or the pause control. Reduced-motion preferences disable automatic rotation. One review is centered without dots; two have two dots; three or more show at most three sliding-window dots. Previous/next controls reach every review. Public review retrieval no longer silently omits reviews after the first 24.

An optional review email is validated and stored only in `reviewer_email`. The public review, project, gallery and count responses do not serialize it. The form explicitly says emails stay private. Removing a review also removes its stored contact email. No email is sent automatically and no marketing opt-in is inferred.

New project now clears the previous brief, imported metadata, manual fallback and saved selections. Metadata request identifiers prevent a late response from filling a new project. The category default is labelled “Choose automatically”; blocked or unreadable public links now offer a short description without suggesting the same website again.

Only the top Finish exploring action remains. Shared-project removal is a full-width secondary action under View community projects. On local homepage arrival at #pricing, initial asynchronous layout changes are observed briefly to maintain the pricing destination. Any user wheel/touch/pointer/keyboard action stops that correction.

Verification: 16 API tests pass, browser checks cover public-email exclusion, review-to-sharing flow, new-project reset, pricing anchor, carousel visibility/motion/dots and mobile layout. Production export was checked with webpack because the bundled environment's Turbopack build cannot spawn its CSS helper. No deployment was performed. Carousel screenshots use browser-only review fixtures, not fabricated public testimonials.

### Neighbouring review previews

The active review remains centered, with dimmed, slightly smaller portions of the immediately previous and next cards clipped at the stage edges. Preview edges can be clicked. A single review has neither neighbour. The first has only a next preview; the last has only a previous preview. Navigation is bounded, and automatic rotation stops at the last review. The existing maximum-three-dot rule, viewport trigger and reduced-motion behavior remain in place.

### Category detection, setup pacing and persistent state

Category detection now shares a keyword vocabulary between the browser and backend across the listed categories. The form shows its detected category immediately from imported details or a typed brief, allows an override, and asks for a category if nothing matches. This is deterministic matching, not an AI classification service; category selection does not imply source coverage in the small catalog.

The setup sequence now spends about 4.55 seconds progressing through three steps with animated connectors. Each stage waits for its corresponding request as well as its presentation interval; failures return immediately. Reduced-motion visitors have a short, non-animated transition. The previous rotating decoration is removed.

Repeated pricing links are handled centrally in Navigation, including clicks while #pricing is already in the URL. Initial delayed layout changes are followed for a bounded period; visitor wheel/touch/key/pointer interaction ends correction. The demo uses a normal anchor to arrive from /try/. The hero CTA now reads simply Pre-order.

The owner-only project endpoint returns existing review text/name/public status, without the private contact email, so reopening Finish exploring recognizes prior feedback and publication. Unpublishing shows a checkmark confirmation and Done rather than returning to the publication form. Review deletion remains separate from project unpublishing.

The review carousel now uses shorter, overlapping, more visible neighbouring cards behind the raised central card, following the provided visual reference. Boundaries remain finite and no duplicate neighbour is invented for one or two reviews.

Verification: 18 local API tests, 85 licensing tests, TypeScript/webpack build and browser regression checks passed. The wording-only live licensing Worker update was published separately as version cf64a415-4481-4ed1-8618-0d83e52e2162. Website and discovery demo changes remain local. New Checkout descriptions preserve first-year delivery and optional currency-specific renewal; the submit note shows only the target launch date, without repeated credit messages.

### Workspace refinement and animated review stack

The review carousel now retains its cards in the DOM and transitions their position and scale over 1.1 seconds rather than replacing the active card. It advances automatically every eight seconds while visible, continues back through the list at the end, and no longer stops permanently after a manual selection or hover. Explicit Pause and reduced-motion preferences remain supported. Only existing neighbouring reviews are shown; their complete rounded outlines fit inside the section instead of being clipped. Review stars and active dots use amber rather than mint.

The project-name control now opens an accessible project menu. It lists owned projects, marks the current one, and offers New project and All projects. With one project it shows that workspace and those useful actions. The owner project API no longer silently truncates the list at ten. Keyboard navigation, Escape and outside-click dismissal are supported.

The setup sequence is about 9.45 seconds in normal motion mode. Each step traces a dotted ring, fills the ring, displays its check and flows a connector to the next step. Copy describes what Outloud is doing: reading app details, finding references and setting up the workspace. It does not claim to create an account or run live source searches. Reduced-motion transitions remain short.

Platform controls sit beside the collection controls. Discover contains creative/editorial/account references; Conversations contains audience discussion references. The backend enforces these distinct kinds and a source cannot be returned in both groups. X account references may appear in Discover, while X discussion links appear in Conversations. The current catalog has no Reddit media reference, so Reddit is not displayed as a Discover filter. Media ingestion/playback is not introduced by this design refinement.

No reference is preselected in either view. The inspector mounts only after selection, slides into view, and has visible close and Escape controls on desktop and phone. Selected cards get a mint border/ring. Reference cards have one rounded content area, overlaid platform/save controls and a quiet source link, without separate top and bottom strips. The cards continue to represent actual catalog references, not invented social posts or video frames.

Verification: 20 API tests, webpack build, `check-workspace-refinement.cjs` and `check-review-stack-motion.cjs`. Screenshots and example reviews in those checks are browser fixtures only; no public reviews, projects, quota or production deployments were changed.

### Local funnel and layout fixes (2 November)

- `/analytics/` is a local reporting page. Anonymous session IDs (per browser tab), allowlisted action/stage names, and two page labels only. No project names, briefs, emails, source URLs or query strings are collected. Thirty-day retention, duplicate event IDs ignored, 300 events/session/hour. Browser exits are best-effort; last recorded stage is a clue, not a definitive abandonment count. Developer/browser QA activity is included and labelled on the report. The collector and report remain local and are not production analytics yet. Cloudflare Web Analytics continues to cover the published site independently.
- Discovery and Conversations share one selection-driven detail rail, aligned with the filters. No initial detail. Desktop rail stays right; phones use a dismissible overlay. Open original/Save are neutral, Pre-order is mint. Clean edge-to-edge editorial covers, not fabricated social media thumbnails. Removed Web as a social platform filter.
- Review dwell is 4.2 seconds (was 8), with 1.1-second movement; only rotates in view and respects reduced motion.
- Preparation uses one fixed 44px ring track, with a centred connector. Dots trace, fill, then connect to the next step.
- Next development mode proxies `/api/purchase/*` to the loopback discovery service's allowlisted commerce bridge. The bridge uses the existing hosted live checkout and its existing protections; no Stripe keys are exposed. GET pricing/availability can be verified without creating a checkout. Clicking purchase opens LIVE checkout; manually paying would be a real purchase. Production static export retains the existing Pages functions, not this dev rewrite. Do not test it with a real card unintentionally. No live reservations or charges created by automated QA.
- No site deployment was performed.

### Conversation feeds and saved scope

- Reddit uses a community header, title and three-line body preview. X uses an author-led layout with text inset below the avatar. “See more” selects the item and opens the existing right rail. No invented votes, reply counts, timestamps or user photos.
- Saved badges count only returned items in the current Discover/Conversations view and selected platform. Stale IDs and other-view saves do not inflate the badge. Empty saved states explain the scope instead of showing a missing-content feedback button.
- Optional source media renders only when an HTTPS image/video URL is actually supplied. The current curated catalog contains no video files; this does not add live platform ingestion.
- Reference rail restored to first-card height, per the latest correction. A compact mint curved arrow animates toward the pre-order link, with reduced-motion support.

### Full reference pages (2 November, latest interaction)

Selection now navigates to a dedicated reference page rather than a desktop rail/mobile overlay. Discover and Conversations retain their own feeds and filters on return. History Back/Forward and Escape return correctly; saving also works from the reference page. Original/catalog reference, catalog notes, and Make it yours form three columns on large screens, two on tablets, and one on phones. The creation formats are informational and do not send generation requests; the full-app pre-order message belongs inside Make it yours. Do not invent transcripts, frame analysis, engagement metrics or playable video where the catalog has none. `check-full-reference-page.cjs` supersedes the prior inspector-only interaction assertions.

Checkout verification remains server-side: the secure HttpOnly checkout cookie (24-hour max age) identifies the browser’s order, never payment status. Signed Stripe events and server-to-Stripe reads determine payment status. Checkout expiry is currently 1,860 seconds (31 minutes). An expired event releases unpaid holds without a browser return; availability/start reconcile overdue holds if needed. The local cross-tab return fix requests early cancellation for the browser’s own unpaid checkout, with retries. No updated website/demo has been published.


## Product understanding and matching — local build, 3 November 2026

- Up to ten references total (six Discover, four Conversations); no category-only padding.
- Confirmed audience, problem and up to eight features persist with each private project.
- Website metadata includes page title/description, headings, subtitle when present, icon and publisher-declared software/product facts from JSON-LD. Google Play uses these public page fields when exposed, with the existing manual fallback when unavailable.
- App Store extraction retains description, categories, screenshots, languages, developer, version and formatted price when provided. Missing fields remain missing.
- Research reuses cached extraction for the exact supplied URL. No extra fetch during research. Source provenance stays private and is not included in gallery cards.
- Matching uses confirmed context and extracted descriptions/headings, and attaches matched terms and a match reason. These are catalog matches, not semantic AI research or verified engagement rankings.
- Source retrieval for fresh Instagram/TikTok/X/Reddit posts is still outstanding. The current catalog does not establish live trend coverage. No paid API calls or generation are enabled.
- Verification: 28 API tests and browser fixture flow in artifacts/check-product-profile.cjs. Nothing deployed.

### Reference navigation
Discover opens the full reference page; Conversations opens a closable side panel aligned with the feed. Video sources offer Video/Image/X post/Reddit; visual covers and image sources offer Image/X post/Reddit; text discussions offer X post/Reddit.


## Demo pacing and completion — 3 November 2026

- Three preparation stages have progressively longer tracing/filling durations (roughly 12 seconds total at normal motion). Reduced-motion users skip long animation waits.
- A short workspace skeleton transition precedes reference cards. No fake media or results are added.
- Completion now opens a research summary with the founding offer when references exist. Reviews and project sharing are independent secondary actions. Empty research sessions report the coverage gap instead of presenting a successful result.
- Matching now requires at least two source-keyword matches and ignores generic words found only in a source summary. Watchers exposed a budgeting false-positive on “spending”; a regression test covers this.
- Relevant Instagram, TikTok and X references are preferentially represented when the catalog contains them. No platform quota is filled with irrelevant material. Combined maximum remains ten.
- Older private workspaces are reranked on opening (match_version=2), without network calls or quota consumption.
- Verified with 31 API checks, browser flow including skeleton and completion dialog, and webpack production build. Local only, not deployed. Fresh platform retrieval remains outstanding.


## Live public-index research — 3 November 2026 (supersedes catalog-only mode)

Local launch: `OUTLOUD_LOCAL_TESTING=1 OUTLOUD_LIVE_SEARCH=1` with the existing uvicorn command. The API remains loopback-only. This is not deployed.

- Existing projects show the skeleton on reopening, including while their first live search runs.
- Four parallel Exa hosted MCP search calls use the project's description, audience, problem and features. Separate queries target Reddit, X, Instagram and TikTok. No name/category-only lookup, paid fallback or generation.
- Accept only original post permalinks on those four platforms. Preserve source excerpts, publisher attribution when available, links and indexed publication dates. Do not fabricate likes/views, media or trend claims.
- Deduplicate canonical links and reject unrelated titles/excerpts. Prefer a platform mix when relevant results exist; return at most ten combined results. Do not force a missing platform.
- Six-hour cache is keyed by owner, full project context and search version. Reopening the same workspace reuses its own results; different briefs cannot share cached workspace data. Separate products may naturally find some of the same public posts.
- Global local-demo limit: 80 search requests/day, four reserved per fresh search. This bounds usage at 20 uncached research runs/day, independent of the project-creation allowance. The free provider may impose tighter limits. No bypass, key rotation or paid automatic fallback.
- Provider failure leaves the project saved and returns an explicit retryable error. It never silently falls back to irrelevant catalog cards. No public launch until reliability and media/engagement limitations are reviewed.
- Watchers tested against the actual service: 10 public-index results (1 Instagram, 3 TikTok, 6 Reddit). No matching X posts returned. Proof in artifacts/watchers-live-proof.json, actual-browser screenshots in artifacts/watchers-live-discover.png and artifacts/watchers-live-conversations.png.
- Search snippets establish discoverability/relevance, not verified popularity or conversion. Media playback/thumbnail access and verified engagement require further integration. No false playback controls or fake metrics.
- 45 API checks passed; actual-browser test checks existing project skeleton, live results, Discover formats and Conversations side panel. Webpack build passed.

Provider references: https://docs.exa.ai/reference/exa-mcp (keyless free rate-limited trial); https://docs.tavily.com/documentation/api-credits (possible keyed alternative, not configured or charged). Tavily's 1,000 free monthly credits would support roughly 250 four-basic-query trials; at $0.008/credit the same request plan costs $0.032/trial after free credits, excluding any additional extraction or media services.

### November 3 local UI follow-up

- Reopening a project immediately renders the Discover workspace. Its feed contains skeleton cards during the request; there is no separate opening screen.
- The demo header carries a compact Beta badge on every demo screen.
- Discover cards fetch lazy thumbnail metadata and display a real image, never an embedded player. Selecting the card opens the full reference page and mounts the provider's player there.
- Thumbnail lookup accepts only social posts present in the current visitor's saved research results; requests are bounded, rate limited and metadata-cached for 30 minutes. No video is downloaded or hosted. Missing thumbnails use a neutral link, not a generated caption poster.
- Public search matching now requires problem-specific overlap, cleans duplicated titles/index wrappers, excludes posts with known dates older than twelve months, and displays valid publication dates separately. Unknown dates are not claimed to be recent. Coverage is still source-dependent: the latest Watchers check returned one Instagram post and four Reddit discussions, with no qualifying TikTok/X results. Relevance is not evidence of popularity.
- Local verification: 52 API tests passed; browser check verified inline skeletons, a successfully loaded Instagram thumbnail, zero feed iframes and a player only after opening its reference. No production deployment.
