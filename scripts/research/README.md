# Local collected-first research evaluation

No deployment or new paid Apify collection is enabled by these changes.

To inspect already verified results locally without paid execution, run the
backend Python environment with `scripts/research/serve-local.py`. It preserves
the research configuration on restart and reports `cached_only: true` at
`http://127.0.0.1:8766/health`. It does not promise fresh results for a new brief.

## Retrieval

- A complete product brief produces a cached model with eighteen search phrases, suggested subreddits and adjacent topics. Suggestions are not claimed to be verified communities. Three optional competitor names/links are accepted in project setup and included in search and evaluation.
- Public post facts are stored separately from private product models and verdicts. All retrieved candidates enter the store before shortlisting. Corpus retrieval retains up to ninety days of collection history; actual publication-age gates still apply.
- Duplicate URLs and old/undated audience discussions are excluded before embeddings. Discussions remain limited to the last thirty days. Up to 300 eligible candidates can be embedded; at most fifty proceed to semantic evaluation. Promotions are routed to competitors, not audience leads.
- Gemini embedding vectors are cached by text, task and model. Query and document vectors are distinct. If embeddings fail, the audit explicitly reports lexical fallback.
- Verdicts are cached by complete product brief, source ID/content, model and policy. Reusing a verdict for a different product would be incorrect. Unchanged inputs do not expire merely because six hours passed.
- Checked results stream through local progressive-job snapshots; raw candidates and locked post contents do not. Authorization is checked on every poll. There are at most two active jobs.
- Direct / Adjacent / Related describes product-problem fit, not a probability or performance claim. These labels never bypass intent or freshness checks.

## Measured engagement

Observations retain their actual retrieval timestamp. Relative performance uses the median of at least ten other measured posts from the same Reddit community or social creator at similar publication ages. Growth requires at least two real observations one hour apart. Missing baselines remain explicitly insufficient; the existing absolute-count fallback remains in place until a baseline exists. Neither synthetic history nor inferred metrics are generated.

## Collection

Run with the backend Python environment:

```
python scripts/research/collect-public.py --once
python scripts/research/collect-public.py --watch
```

The launcher reads the existing private configuration outside the repo. The local watcher ticks every thirty minutes, makes at most four public-index queries per tick, and shares the eighty-query daily pool with foreground research. Foreground research conservatively reserves twenty-four query slots. The collector never starts Apify runs or creates new problem models. It only refreshes niches already researched. It is a local process, not deployed infrastructure or a production scheduling guarantee.

## Evaluation limits

The provider ledger retains conservative reservations against the existing $5 lifetime evaluation ceiling. Reservations are not invoices or actual usage charges. No new Apify runs, billing upgrades, production deployments or new data-provider accounts are part of this evaluation.

The corpus is based on available index text and cached platform data. It does not imply access to full Reddit/X feeds, complete original post bodies, video transcripts or frame analysis. These remain coverage limitations, not UI features that can be solved by adding placeholder content.

Evidence: `artifacts/watchers-staged-retrieval-check.json`. Backend tests include corpus reuse, metadata preservation, isolated verdicts, embeddings caching, baseline/growth requirements, collection bounds and progressive-job ownership.
