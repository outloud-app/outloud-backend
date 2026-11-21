"""Bounded, deterministic product understanding. No model calls or invented facts."""
import re

STOP = set('the and for with from your this that into have helps help people app software product website their they you are its can our who what more'.split())

def clean(value, limit=1200):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', str(value or ''))).strip()[:limit]

def terms(text):
    return {word for word in re.findall(r'[a-z][a-z-]{2,}', text.lower()) if word not in STOP}

def research_project(project, metadata=None):
    """Enrich internal research with publisher facts without rewriting the user's brief."""
    metadata = metadata or {}
    details = metadata.get('details') or {}
    product = details.get('product') or {}
    facts = [clean(metadata.get('title'), 180), clean(details.get('subtitle'), 300),
             clean(details.get('description') or product.get('description') or metadata.get('description'), 8000)]
    facts += [clean(value, 200) for value in details.get('headings', [])[:12]]
    # Contact, legal and subscription boilerplate are not the customer's job.
    text = ' '.join(value for value in facts if value)
    text = re.split(r'\b(?:privacy policy|terms of use|terms of service|if you have any questions|contact us at)\b', text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r'\S+@\S+', '', text).strip()
    if not text:
        return project
    description = project.description + '\nPublisher details: ' + text
    # Internal context can exceed the public form's 1200-character input limit.
    return project.model_copy(update={'description': description[:10000]})

def research_context(project):
    """One grounded product job is shared by retrieval and source evaluation."""
    from research_retrieval import cached_model
    model = cached_model(project) or {}
    understanding = model.get('product_understanding') or {}
    return {'product_name': project.name, 'customer_problem': project.problem or understanding.get('problem') or project.description,
            'audience': project.audience or understanding.get('audience', ''),
            'product_job': understanding.get('job') or project.description,
            'publisher_context': project.description, 'features': project.features,
            'known_competitors': getattr(project, 'competitors', []), 'research_keywords': getattr(project, 'keywords', []),
            'followed_sources': [source.model_dump() for source in getattr(project, 'followed_sources', [])]}

def grounded_understanding(project, value):
    """Keep model inferences only when tied to an exact publisher/user excerpt."""
    if not isinstance(value, dict):
        raise ValueError('Missing product understanding.')
    source = ' '.join([project.name, project.description, project.problem, project.audience, *project.features])
    result = {}
    for field in ('job', 'problem', 'audience'):
        claim, quote = value.get(field), value.get(field + '_quote')
        if not isinstance(claim, str) or not 5 <= len(claim) <= 600:
            raise ValueError('Incomplete product understanding: ' + field)
        if not isinstance(quote, str) or len(quote) < 12 or quote not in source:
            raise ValueError('Product understanding lacks source evidence: ' + field)
        result[field], result[field + '_quote'] = claim.strip(), quote
    return result

def profile_for(project):
    fields = project.model_dump()
    audience = clean(fields.get('audience'), 240)
    problem = clean(fields.get('problem'), 400)
    features = [clean(item, 180) for item in fields.get('features', []) if clean(item, 180)][:8]
    seeds = fields.get('keywords', [])
    text = ' '.join([project.name, project.description, audience, problem, *features, *seeds])
    return {'name': project.name, 'platform': project.platform, 'description': project.description,
            'audience': audience, 'problem': problem, 'features': features,
            'research_keywords': seeds, 'keywords': sorted(terms(text))[:80], 'source_url': project.url,
            'confirmed': True, 'unknown': [key for key, value in [('audience', audience), ('problem', problem), ('features', features)] if not value]}

def rank_catalog(project, catalog, keywords, metadata=None):
    profile = profile_for(project)
    metadata = metadata or {}
    details = metadata.get('details', {})
    extracted = ' '.join([clean(details.get('description'),10000), *[clean(h,240) for h in details.get('headings',[])[:12]]])
    words = set(profile['keywords']) | terms(extracted)
    profile['public_details'] = details
    profile['provenance'] = metadata.get('provenance', {})
    category = project.category
    if category == 'auto':
        scores = {key: len(words & set(items)) for key, items in keywords.items()}
        category = max(scores, key=scores.get) if scores and max(scores.values()) else 'other'
    ranked = []
    for source in catalog:
        if category not in source['categories']:
            continue
        overlap = sorted(words & terms(' '.join(source.get('keywords', []))))
        # Category membership alone is not evidence of relevance to this product.
        if len(overlap)<2:
            continue
        item = dict(source)
        item['match_reason'] = 'Matches your product details: ' + ', '.join(overlap[:4]) + '.'
        item['matched_terms'] = overlap[:8]
        item['evidence'] = {'type': 'catalog_reference', 'engagement_verified': False}
        ranked.append((len(overlap), item))
    ranked.sort(key=lambda row: (-row[0], row[1]['id']))
    candidates = [item for _, item in ranked if item['section']=='discover' and item['kind']!='Discussion']
    # Prefer source diversity only within the relevant candidate pool.
    discover = []
    for platform in ('Instagram', 'TikTok', 'X'):
        candidate = next((item for item in candidates if item['platform']==platform), None)
        if candidate:
            discover.append(candidate)
    discover += [item for item in candidates if item not in discover][:6-len(discover)]
    conversations = [item for _, item in ranked if item['section']=='conversations' and item['kind']=='Discussion'][:4]
    return {'discover':discover, 'conversations':conversations, 'mode':'curated', 'limit':10,
            'match_version':2, 'category':category, 'profile':profile, 'checked': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()}
