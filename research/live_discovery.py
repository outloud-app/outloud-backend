"""Native-first research with explicit provider gates and bounded spend.
Public-index acquisition is an opt-in diagnostic, never a silent fallback.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from urllib.parse import quote, urlsplit, urlunsplit
import httpx
from product_profile import clean, profile_for, terms
from research_quality import select_results, MAX_RESULTS, LANE_LIMITS

ENDPOINT='https://mcp.exa.ai/mcp'
VERSION=31

class ResearchUnavailable(Exception):
    pass


def provider_cache_signature():
    from research_providers import configuration,EVALUATION_VERSION
    config=configuration()
    from research_routing import mode
    import os
    execution=':execution=cached_only' if os.environ.get('OUTLOUD_RESEARCH_CACHE_ONLY')=='1' else ''
    return ':retrieval='+mode()+execution+(f":providers:media={config['media']}:evaluation={config['evaluation']}:policy={EVALUATION_VERSION}" if config['enabled'] else '')


def cache_key(project):
    return hashlib.sha256(json.dumps(project.model_dump(),sort_keys=True).encode()).hexdigest()


def search_plan(project):
    problem=clean(project.problem or project.description,650)
    audience=clean(project.audience,220)
    seeds=', '.join(getattr(project, 'keywords', []))
    context=f"Audience: {audience}. Problem to solve: {problem}"
    if seeds: context += f". Related research topics: {seeds}"
    since=datetime.now(timezone.utc).year-1
    short_problem=re.split(r'[.!?]',problem)[0][:160]
    # Prefer a concrete task phrase over a long bundle of niche keywords.
    phrases=re.findall(r'\b(?:watch|watching|monitoring|tracking|logging|manually|missing|finding|searching)\b[^.!?]{4,65}',problem,re.I)
    social_focus=phrases[-1] if phrases else short_problem
    query_context=f'{short_problem}. {clean(audience,90)}'
    objective=(f'Find original public posts from the last 12 months, prioritising the last 90 days. {context}. '
       'For conversations match the frustration, task or desired outcome. For creative media also find entertaining niche experiences, useful techniques and visual demonstrations for the same audience; mentioning the exact software features is not required. '
       'Exclude profit guarantees, trading signals for sale, unrelated industry news and empty profile/search pages. '
       'For social videos/images find relevant niche inspiration as well as posts about that problem. Competitors must be products solving the same customer job. '
       'For discussions find people asking for help or describing that problem. Preserve original text, publication date, author, '
       'and original post URL. Do not invent engagement, media or popularity.')
    return [
        ('Reddit',f'site:reddit.com Find Reddit discussions where people describe this problem or ask for related tools: {context}'),
        ('X',f'site:x.com after:{since}-11-01 people discussing this frustration or asking for solutions: {context}'),
        ('Instagram',f'site:instagram.com {social_focus} solutions'),
        ('TikTok',f'site:tiktok.com {social_focus} solutions'),
    ],objective


def call_search(query,objective):
    payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'web_search_exa','arguments':{'query':query,'objective':objective,'numResults':8}}}
    with httpx.Client(timeout=18,follow_redirects=False) as client:
        response=client.post(ENDPOINT,headers={'Accept':'application/json, text/event-stream'},json=payload)
    if response.status_code!=200:
        raise ResearchUnavailable('Public search is temporarily unavailable. Please try again shortly.')
    body=response.text
    if len(body)>1500000:
        raise ResearchUnavailable('The search response was too large. Please try again.')
    if 'data: ' in body:
        envelopes=[]
        for line in body.splitlines():
            if line.startswith('data: '):
                try: envelopes.append(json.loads(line[6:]))
                except ValueError: pass
        envelope=next((item for item in envelopes if isinstance(item,dict) and ('result' in item or 'error' in item)),{})
    else:
        envelope=response.json()
    if envelope.get('error') or envelope.get('result',{}).get('isError'):
        raise ResearchUnavailable('Public search is busy. Please try again shortly.')
    return '\n'.join(block.get('text','') for block in envelope.get('result',{}).get('content',[]) if block.get('type')=='text')


def fresh_query(platform, query, lane=None):
    """Search hints narrow acquisition; only original publication proves recency."""
    days = 30 if lane=='conversations' or (lane is None and platform in ('Reddit','X')) else 365
    cutoff = (datetime.now(timezone.utc)-timedelta(days=days)).date().isoformat()
    return query+' after:'+cutoff


def semantic_search_plan(project, brief, community_feeds=False):
    plan=[]
    communities=brief.get('subreddits', [])[:3]
    for index, phrase in enumerate(brief['conversations'][:3]):
        if community_feeds and index<len(communities):
            plan.append(('Reddit', 'community-feed:'+communities[index]))
        else:
            domain='reddit.com/r/'+communities[index] if index<len(communities) else 'reddit.com'
            plan.append(('Reddit', 'site:'+domain+' '+phrase))
    plan.extend(('Reddit','site:reddit.com '+phrase) for phrase in brief['conversations'][3:6])
    plan.extend(('X','site:x.com '+phrase) for phrase in brief['conversations'][:4])
    for platform,domain in (('Instagram','instagram.com'),('TikTok','tiktok.com')):
        plan.extend((platform,'site:'+domain+' '+phrase) for index,phrase in enumerate(brief['for_you']) if index in (0,2,4,5))
        known=getattr(project,'competitors',[])
        plan.extend((platform,'site:'+domain+' '+(known[index]+' ' if index<len(known) else '')+phrase) for index,phrase in enumerate(brief['competitors'][:2]))
    return plan[:24]


def post_identity(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return None
        host=parsed.hostname.lower().removeprefix('www.')
        path=parsed.path
        if host=='reddit.com' and re.search(r'/r/[^/]+/comments/[^/]+',path):platform='Reddit'
        elif host in ('x.com','twitter.com') and re.search(r'/[^/]+/status/\d+',path):platform='X'
        elif host=='instagram.com' and re.search(r'^/(p|reel|reels)/[^/]+',path):platform='Instagram'
        elif host=='tiktok.com' and re.search(r'^/@[^/]+/video/\d+',path):platform='TikTok'
        else:return None
        return platform,urlunsplit(('https',host,path.rstrip('/')+'/', '', ''))
    except (ValueError,AttributeError):return None


def plain_excerpt(text,title=''):
    # Remove index wrappers and comment chains while preserving the author's prose.
    text=re.split(r'\n(?:\.\.\.|\*\*u/|>\s)',text)[0]
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    text=re.sub(r'[*_`#]','',text)
    text=re.sub(r'TikTok - Make Your Day','',text)
    text=re.sub(r'Posted by\s+u/[^ ]+\s+in\s+r/[^ ]+.*?\bUTC\s*','',text,flags=re.I)
    text=re.sub(r'^Profile\s+More\s+Log in\s+©\s+\d{4}\s+TikTok\s*','',text,flags=re.I)
    text=re.sub(r'(?m)^---\s*$','',text)
    lines=[]
    title_key=re.sub(r'[^a-z0-9]','',title.lower().split(' : r/')[0])
    for line in text.splitlines():
        line=line.strip()
        key=re.sub(r'[^a-z0-9]','',line.lower())
        if not line or key==title_key:continue
        if re.match(r'^(?:Posted by|Published:|Author:|URL:|Title:|Image \d+:|\d+ (?:points|comments|votes)\b)',line,re.I):continue
        if re.match(r'^(?:u/|r/).*?[·•]\s*\d+ (?:points|comments)',line,re.I):continue
        lines.append(line)
    result=clean(' '.join(lines),8000)
    simple_title=title.split(' : r/')[0].strip()
    if result.lower().startswith(simple_title.lower()):result=result[len(simple_title):].lstrip(' .:–—-|')
    return result


def publication(value):
    if not isinstance(value,str) or not value.strip():return None,None
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
        age=(datetime.now(timezone.utc)-date).days
        return date.isoformat(),age
    except (ValueError,TypeError):return None,None


def problem_match(project,text):
    # Problem words are mandatory; broad category overlap alone cannot qualify a post.
    def stems(value):
        aliases={'notification':'alert','notifications':'alert','notified':'alert','notify':'alert','alerts':'alert',
                 'monitoring':'monitor','monitors':'monitor','watching':'monitor','watch':'monitor','watches':'monitor',
                 'scanning':'scan','scans':'scan','scanner':'scan','scanners':'scan',
                 'patterns':'setup','pattern':'setup','setups':'setup','missed':'miss','missing':'miss'}
        return {aliases.get(word,re.sub(r'(?:ing|ed|s)$','',word) if len(word)>5 else word) for word in terms(value)}
    problem=stems(project.problem or project.description)
    words=stems(text)
    overlap=problem & words
    generic={'app','software','product','tool','tools','potential','opportunities','users','automatically'}
    generic |= {'all','day','days','time','hours','often','never','while','away','need','just','have','more'}
    generic |= {re.sub(r'(?:ing|ed|s)$','',word) if len(word)>5 else word for word in generic}
    specific=overlap-generic
    return specific, len(overlap)


def social_preview(platform,url):
    # Official embedded players handle original media; page URLs are never video files.
    path=urlsplit(url).path
    if platform=='TikTok':return {'provider':'tiktok','id':path.rstrip('/').split('/')[-1]}
    if platform=='Instagram':return {'provider':'instagram','id':path.strip('/').split('/')[1],'path':path.strip('/').split('/')[0]}
    return None


def author_label(value, platform, url):
    value=clean(value,100)
    if value.lower() not in ('','n/a','unknown','none','null'):
        return value
    path=urlsplit(url).path
    if platform in ('TikTok','X'):
        handle=path.strip('/').split('/')[0]
        return handle if handle.startswith('@') else '@'+handle
    if platform=='Reddit':
        community=re.search(r'/r/([^/]+)',path)
        return 'r/'+community.group(1) if community else 'Reddit discussion'
    return 'Instagram post'


def reddit_metadata_metrics(text):
    """Only the index's explicit post header, never numbers quoted in the body."""
    normalized=re.sub(r'[*_`#]','',text)
    header=re.search(r'(?:^|\n)Posted by\s+u/[^\n]{0,400}?\bUTC\b',normalized,re.I)
    if not header:return None
    score=re.search(r'(?<![\w.])(-?\d[\d,]*)\s+points\b',header.group(),re.I)
    comments=re.search(r'(?<![\w.])(\d[\d,]*)\s+comments\b',header.group(),re.I)
    if not score and not comments:return None
    metrics={'provider':'exa_index_metadata','checked_at':datetime.now(timezone.utc).isoformat()}
    if score:metrics['score']=int(score.group(1).replace(',',''))
    if comments:metrics['comments']=int(comments.group(1).replace(',',''))
    return metrics


def parse_results(text,project):
    from research_providers import configuration
    provider=configuration()
    semantic=provider['enabled'] and provider['evaluation']
    context=terms(' '.join([project.description,project.audience,project.problem,*project.features]))
    sources=[]
    for block in re.split(r'(?m)^Title:\s*',text)[1:]:
        title=clean(re.split(r'(?m)^URL:',block)[0],400)
        title=re.sub(r'\s*(?:\| Instagram|\| TikTok|: r/[^ ]+)$','',title).strip()
        url=re.search(r'(?m)^URL:\s*(https://\S+)',block)
        identity=post_identity(url.group(1)) if url else None
        if not identity:continue
        platform,canonical=identity
        raw=re.split(r'(?m)^(?:Highlights|Text|Content):\s*',block,maxsplit=1)
        excerpt=plain_excerpt(raw[1],title) if len(raw)>1 else ''
        if title.lower() in ('n/a','unknown','none','null','tiktok','instagram'):
            title=clean(excerpt,160)
        if len(title)<8 or (len(excerpt)<30 and platform not in ('Instagram','TikTok')):continue
        if len(excerpt)<30 and len(title)<30:continue
        overlap=sorted(context & terms(title+' '+excerpt))
        title_words=terms(title)-{'time','day','hours','looking','using','new','real','good','software','building'}
        specific,problem_score=problem_match(project,title+' '+excerpt)
        if not semantic and (len(overlap)<2 or len(specific)<2):continue
        author=re.search(r'(?m)^Author:\s*(.+)',block)
        published=re.search(r'(?m)^Published:\s*(\S+)',block)
        published_at,age=publication(published.group(1) if published else None)
        if age is not None and (age>365 or age < -2):continue
        video=platform=='TikTok' or platform=='Instagram' and '/reel' in canonical
        section='conversations' if platform in ('Reddit','X') else 'discover'
        competitor=section=='discover' and bool(re.search(r'\b(?:our|my|try|built|introducing|download)\b',title+' '+excerpt,re.I)) and bool(re.search(r'\b(?:app|software|platform|scanner|service|tool)\b',title+' '+excerpt,re.I))
        sources.append({'id':'live-'+hashlib.sha256(canonical.encode()).hexdigest()[:20], 'platform':platform,
          'kind':'Video' if video else 'Image' if platform=='Instagram' else 'Discussion',
          'title':title, 'author':author_label(author.group(1) if author else '',platform,canonical),
          'url':canonical,'summary':excerpt,'competitor':competitor,'section':section,'tone':'cream',
          'match_reason':'Addresses the problem you described: '+', '.join(sorted(specific)[:4])+'.','matched_terms':overlap[:8],
          'published_at':published_at,'preview':social_preview(platform,canonical),
          'evidence':{'type':'indexed_public_post','provider':'Exa','engagement_verified':False,'excerpt':True},'_score':problem_score+len(specific)*3+(3 if age is not None and age<=90 else 0)})
        if platform=='Reddit' and len(raw)>1:
            metrics=reddit_metadata_metrics(raw[1])
            if metrics:sources[-1]['metrics']=metrics
    return sources


def revalidate_candidates(project,candidates):
    """Apply today's URL, excerpt, age and problem gates to older cached candidates."""
    from research_providers import configuration
    config=configuration()
    semantic=config['enabled'] and config['evaluation']
    output=[]
    for original in candidates:
        source=dict(original)
        identity=post_identity(source.get('url',''))
        if not identity or identity[0]!=source.get('platform'):continue
        source['url']=identity[1]
        if (source.get('evidence') or {}).get('type')!='original_platform_post':
            source['title']=re.sub(r'\s*:?\s+r/[^ ]+\s*$','',source.get('title','')).strip()
            source['summary']=plain_excerpt(source.get('summary',''),source.get('title',''))
        specific,_=problem_match(project,source.get('title','')+' '+source['summary'])
        # In semantic mode, retrieval must not discard broader niche inspiration
        # merely because its caption lacks the app's exact problem vocabulary.
        # These remain candidates, never recommendations without evaluation.
        if not semantic and len(specific)<2 and not source.get('evaluation') and not (source['platform'] in ('Instagram','TikTok') and problem_match(project,source.get('title','')+' '+source['summary'])[1]>=2):continue
        _,age=publication(source.get('published_at'))
        if age is not None and (age>365 or age < -2):continue
        source['matched_terms']=sorted(specific)
        source['author']=author_label(source.get('author',''),source['platform'],source['url'])
        output.append(source)
    return output


def merge_candidates(candidates):
    """An index snippet cannot overwrite an original caption and measured media."""
    unique={}
    for source in candidates:
        previous=unique.get(source['url'])
        def evidence_rank(item):
            evidence=item.get('evidence') or {}
            return (evidence.get('type')=='original_platform_post',bool(evidence.get('engagement_verified')),bool(item.get('media')))
        if previous is None or evidence_rank(source)>evidence_rank(previous):unique[source['url']]=source
    return list(unique.values())


def balanced_candidates(project,candidates,limit=24):
    """Reserve evaluation room for audience needs, creative media and competitors.

    These heuristics retrieve candidates only. They never override semantic selection.
    """
    from research_quality import route_source,attention
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError('Candidate balance limit must be one to one hundred.')
    def rank(source):
        specific,overlap=problem_match(project,source.get('title','')+' '+source.get('summary',''))
        _,age=publication(source.get('published_at'))
        explicit_request=source['platform'] in ('Reddit','X') and bool(re.search(r'\b(?:looking for|is there|does anyone|can anyone|recommend(?:ations)?|any (?:service|tool|app))\b',source.get('title','')+' '+source.get('summary',''),re.I))
        return (attention(source)['status']=='qualified',explicit_request,len(specific)*3+overlap,
                age is not None and age<=90,source.get('url',''))
    groups=[]
    for platform in ('Reddit','X','Instagram','TikTok'):
        pool=sorted([s for s in candidates if s['platform']==platform],key=rank,reverse=True)
        lanes={lane:[s for s in pool if route_source(s)==lane] for lane in ('conversations','discover','competitors','reject')}
        selected=[]
        # Round robin keeps a flood of competing builder posts from removing the
        # only solution request or measured creative before the model sees it.
        order=('discover','competitors','conversations','reject') if platform in ('Instagram','TikTok') else ('conversations','competitors','reject','discover')
        for index in range(len(pool)):
            for lane in order:
                if index<len(lanes[lane]):selected.append(lanes[lane][index])
        groups.append(selected)
    output=[]
    for index in range(max((len(g) for g in groups),default=0)):
        for group in groups:
            if index<len(group):output.append(group[index])
            if len(output)>=limit:return output
    return output


def research_live(project,search=call_search,prior_candidates=(),on_progress=None,before_search=None):
    import os
    # Opening an already researched product must not depend on another paid
    # planning, embedding or collection call. This explicit local mode reads
    # exact-product verdicts and still applies current intent/date checks.
    if os.environ.get('OUTLOUD_RESEARCH_CACHE_ONLY')=='1':
        from workspace_refresh import refresh
        snapshot={'discover':[source for source in prior_candidates if source.get('section')=='discover'],
                  'conversations':[source for source in prior_candidates if source.get('section')=='conversations'],
                  'mode':'collected_store',
                  'search_version':VERSION,'category':project.category,'profile':profile_for(project),
                  'checked':datetime.now(timezone.utc).isoformat()}
        from research_routing import mode
        result=refresh(project,snapshot,previous_snapshot={'discover':[],'conversations':[]},native_only=mode()=='native')
        result['research_issues']=['Fresh collection is paused; showing previously verified sources only.']
        result['quality_report']['launch_ready']=False
        result['quality_report']['blockers']=list(dict.fromkeys(result['quality_report']['blockers']+result['research_issues']))
        if on_progress:on_progress({'stage':'ready','discover':result['discover'],'conversations':result['conversations']})
        return result
    from research_routing import mode,media_plan
    # An injected test/search adapter remains a deliberate indexed diagnostic.
    acquisition=mode() if search is call_search else 'indexed'
    from research_quality import is_native_source
    plan,objective=search_plan(project)
    planning_mode='problem_phrases'
    from research_providers import configuration,search_brief
    provider=configuration()
    sources=[];failures=[];native_issues=[];reusable=[];collection_counts=[]
    from research_providers import remember_public_sources,remembered_candidates
    # Store-first retrieval: public facts are reusable, product verdicts remain isolated.
    stored=merge_candidates(remembered_candidates(project)+list(prior_candidates))
    if acquisition=='native':stored=[source for source in stored if is_native_source(source)]
    if provider['enabled'] and provider['evaluation']:
        from research_providers import cached_evaluations
        checked=cached_evaluations(project,stored)
        reusable,reuse_report=select_results(project,checked,require_evaluation=True,native_only=acquisition=='native')
        if on_progress and reusable:on_progress({'stage':'collecting','discover':[s for s in reusable if s['section']=='discover'],'conversations':[s for s in reusable if s['section']=='conversations']})
        # A complete checked mix can be served without another network search.
        if reuse_report['launch_ready']:
            return {'discover':[s for s in reusable if s['section']=='discover'],'conversations':[s for s in reusable if s['section']=='conversations'],'quality_report':reuse_report,'research_issues':[],
                'limit':MAX_RESULTS,'lane_limits':dict(LANE_LIMITS),'mode':'collected_store','planning_mode':planning_mode,'search_version':VERSION,'category':project.category,'profile':profile_for(project),'checked':datetime.now(timezone.utc).isoformat(),
                'coverage':{platform:sum(s['platform']==platform for s in reusable) for platform in ('Instagram','TikTok','X','Reddit')},'unavailable_platforms':[],
                'notice':'Matched from collected public posts. Dates and engagement reflect their last retrieval.'}
    if provider['enabled'] and any(os.environ.get(g)=='1' for g in ('OUTLOUD_MEDIA_SEARCH_ALLOWED','OUTLOUD_CONVERSATION_START_ALLOWED')):
        from native_access import require,NativeAccessUnavailable,NativeCapacityUnavailable
        try:require()
        except NativeCapacityUnavailable as error:
            if not reusable:raise ResearchUnavailable(str(error)) from None
            from workspace_refresh import refresh
            snapshot={'discover':[s for s in reusable if s['section']=='discover'],
                      'conversations':[s for s in reusable if s['section']=='conversations'],
                      'mode':'collected_store','search_version':VERSION,'category':project.category,
                      'profile':profile_for(project),'checked':datetime.now(timezone.utc).isoformat(),
                      'research_issues':[str(error)]}
            return refresh(project,snapshot,candidates=stored,native_only=acquisition=='native')
        except NativeAccessUnavailable as error:raise ResearchUnavailable(str(error)) from None
    brief={}
    if provider['enabled'] and provider['evaluation']:
        from provider_budget import BudgetExceeded
        try:
            brief=search_brief(project)
            if acquisition=='indexed':
                plan=semantic_search_plan(project,brief,community_feeds=search is call_search)
            planning_mode='semantic_phrases'
        except BudgetExceeded:
            raise ResearchUnavailable('The approved research budget is reserved. Existing results are preserved.') from None
        except Exception:
            if acquisition!='native':
                raise ResearchUnavailable('Product analysis is temporarily unavailable. Your project is saved; retry research without entering it again.') from None
            # Native adapters plan their own queries using the product brief.
            # A missing indexed search plan must not block those adapters.
            planning_mode='native_product_brief'
    can_plan_native=planning_mode in ('semantic_phrases','native_product_brief')
    plan=plan[:24]
    if on_progress:on_progress({'stage':'collecting','discover':[s for s in reusable if s['section']=='discover'],'conversations':[s for s in reusable if s['section']=='conversations']})
    cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat()
    plan=[(platform,fresh_query(platform,query) if not query.startswith('community-feed:') else query) for platform,query in plan]
    def retrieve(platform,query):
        if before_search:before_search()
        if query.startswith('community-feed:'):
            from community_feeds import fetch_recent
            return fetch_recent(query.split(':',1)[1])
        return parse_results(search(query,objective+(f' Audience discussions must be published on or after {cutoff}. Return publication dates; exclude older or undated discussions.' if platform in ('Reddit','X') else ' Include established popular niche creatives from the last 12 months as well as recent posts.')),project)
    # The connected Apify free account permits five active runs. Leave one
    # slot free instead of launching six actors and losing a whole platform.
    with ThreadPoolExecutor(max_workers=4) as pool:
        def native_media(task):
            rows=discover_native_media(task['phrases'],20,90,task['platform'],task['platform']=='Instagram')
            # Retrieval intent is provenance, not a substitute for evaluation.
            return [{**row,'retrieved_for':task['lane']} for row in rows]
        # Native video search has a distinct authorization gate. Without it,
        # keep using already-collected public sources; never start paid runs.
        import os
        if can_plan_native and os.environ.get('OUTLOUD_MEDIA_SEARCH_ALLOWED')=='1':
            from research_providers import discover_native_media,native_search_terms
            try:
                native_terms=native_search_terms(project)
                native={pool.submit(native_media,task):(task['platform'],task['lane'])
                        for task in media_plan({**native_terms,'brief':brief},project)}
            except Exception:
                native={};native_issues.append('Native search planning is temporarily unavailable.')
        else:
            native={}
            if acquisition=='native':native_issues.append('Native Instagram/TikTok acquisition is disabled; web search was not substituted.')
        if can_plan_native and os.environ.get('OUTLOUD_CONVERSATION_START_ALLOWED')=='1':
            from native_conversations import discover as native_discussions,queries_for,ConversationUnavailable
            for platform in ('X','Reddit'):
                try:
                    # Separate searches avoid one broad latest-results list
                    # exhausting the candidate pool. Each is budget-gated.
                    for query in queries_for(project,platform)[:max(1,min(3,int(os.environ.get('OUTLOUD_NATIVE_CONVERSATION_QUERY_LIMIT','1'))))]:
                        native[pool.submit(native_discussions,query,20,90,platform)]=(platform,'conversations')
                except ConversationUnavailable as exc:native_issues.append(str(exc))
                except Exception:native_issues.append(platform+' conversation planning is temporarily unavailable.')
        elif acquisition=='native':native_issues.append('Native Reddit/X acquisition is disabled; web search was not substituted.')
        futures={pool.submit(retrieve,platform,query):platform for platform,query in plan} if acquisition=='indexed' else {}
        for future in as_completed(futures):
            platform=futures[future]
            try:sources.extend(item for item in future.result() if item['platform']==platform)
            except Exception:failures.append(platform)
        for future in as_completed(native):
            platform,lane=native[future]
            try:
                rows=future.result()
                sources.extend(rows)
                collection_counts.append({'platform':platform,'lane':lane,'returned':len(rows),'status':'completed'})
            except Exception as exc:
                collection_counts.append({'platform':platform,'lane':lane,'returned':0,'status':'unavailable',
                                          'http_status':getattr(getattr(exc,'response',None),'status_code',None)})
                from native_conversations import ConversationUnavailable
                native_issues.append(str(exc) if isinstance(exc,ConversationUnavailable) else 'Native source collection has not completed; only checked sources are shown.')
    evaluation_error=None
    from research_providers import configuration,evaluate,enrich_media,remembered_candidates,remember_public_sources
    config=configuration()
    # Keep the evaluation request bounded and stop one platform crowding out the others.
    # Historical matches belong to this exact owner/brief and go through fresh evaluation.
    # Interleave them with new candidates so neither pool crowds out the other.
    historic=stored+revalidate_candidates(project,prior_candidates)
    if acquisition=='native':historic=[source for source in historic if is_native_source(source)]
    combined=[]
    for index in range(max(len(historic),len(sources))):
        if index<len(historic):combined.append(historic[index])
        if index<len(sources):combined.append(sources[index])
    sources=merge_candidates(combined)
    remember_public_sources(sources)
    from research_retrieval import shortlist
    sources,retrieval_report=shortlist(project,sources) if config['enabled'] and config['evaluation'] else (balanced_candidates(project,sources),{'mode':'lexical'})
    media_issues=[]
    if not (config['enabled'] and config['evaluation']):
        sources,media_issues=enrich_media(sources)
    if config['enabled'] and config['evaluation']:
        try:
            def emit_partial(verdicts):
                partial=[{**s,'evaluation':verdicts[s['id']]} for s in sources if s['id'] in verdicts]
                selected,_=select_results(project,reusable+partial,require_evaluation=True)
                on_progress({'stage':'evaluating','discover':[s for s in selected if s['section']=='discover'],'conversations':[s for s in selected if s['section']=='conversations']})
            evaluations=evaluate(project,sources,on_progress=emit_partial) if on_progress else evaluate(project,sources)
            if getattr(evaluations,'unavailable_ids',[]):
                evaluation_error='Some sources could not be evaluated; only independently checked results are shown.'
            for source in sources:
                source.pop('evaluation',None)
                if source['id'] in evaluations:source['evaluation']=evaluations[source['id']]
        except Exception:
            raise ResearchUnavailable('We couldn’t finish evaluating these sources. Your project is saved; retry without re-entering it.') from None
    if config['enabled'] and config['evaluation']:
        from research_providers import media_candidates
        media_pool=media_candidates(sources)
        before={s['id']:(s.get('title'),s.get('summary')) for s in media_pool}
        enriched,media_issues=enrich_media(media_pool)
        changed=[s for s in enriched if before[s['id']]!=(s.get('title'),s.get('summary'))]
        # Platform captions supersede index excerpts: re-evaluate changed text.
        # Never reuse a verdict whose quote refers to the old search snippet.
        try:
            refreshed=evaluate(project,changed) if changed else {}
            if getattr(refreshed,'unavailable_ids',[]):
                evaluation_error='Some updated captions could not be evaluated; those posts were excluded.'
        except Exception:
            refreshed={}
            evaluation_error='Updated captions could not be evaluated; those posts were excluded.'
        for source in changed:
            source.pop('evaluation',None)
            if source['id'] in refreshed:source['evaluation']=refreshed[source['id']]
        by_id={s['id']:s for s in enriched}
        sources=[by_id.get(s['id'],s) for s in sources]
        remember_public_sources(sources)
    # A failed or crowded fresh shortlist must not erase current-policy,
    # independently checked matches from the shared corpus. These decisions
    # were validated against this exact product and unchanged source text above.
    selected,quality=select_results(project,reusable+sources,require_evaluation=config['enabled'] and config['evaluation'],native_only=acquisition=='native')
    if acquisition=='native':
        from conversation_fill import fill
        selected,quality,filled,fill_issues=fill(project,selected,quality,on_progress,brief=brief)
        collection_counts.extend(filled)
        native_issues.extend(fill_issues)
        from competitor_fill import fill as fill_competitors
        selected,quality,publisher_collections=fill_competitors(project,selected,quality)
        collection_counts.extend(publisher_collections)
    quality['retrieval']={**retrieval_report,'acquisition':acquisition,'indexed_queries':len(plan) if acquisition=='indexed' else 0,'native_collections':collection_counts}
    quality['evaluation_failures']=getattr(evaluations,'failure_reasons',[]) if config['enabled'] and config['evaluation'] else []
    media_issues=list(dict.fromkeys(media_issues+native_issues))
    quality['blockers'].extend(media_issues)
    if media_issues:quality['launch_ready']=False
    if evaluation_error:
        quality['launch_ready']=False
        quality['blockers'].append(evaluation_error)
    if not selected:
        raise ResearchUnavailable('We couldn’t retrieve useful public posts for this research yet. Your project is saved; retry research without retyping your details.')
    return {'discover':[i for i in selected if i['section']=='discover'], 'conversations':[i for i in selected if i['section']=='conversations'],
            'quality_report':quality,'research_issues':media_issues+([evaluation_error] if evaluation_error else []),'conversation_window_days':30,'limit':MAX_RESULTS,'lane_limits':dict(LANE_LIMITS),'mode':'native_search' if acquisition=='native' else 'live_search','planning_mode':planning_mode,'search_version':VERSION,'category':project.category,'profile':profile_for(project),
            'checked':datetime.now(timezone.utc).isoformat(),'coverage':{p:sum(i['platform']==p for i in selected) for p in ('TikTok','Instagram','Reddit','X')},
            'unavailable_platforms':failures,'notice':'Original public posts matched to your product. Engagement is shown only when retrieved; media availability varies by source.'}


def fetch_post_preview(url):
    """Read only public preview metadata. Never fetch/host a video or arbitrary URL."""
    from html.parser import HTMLParser
    from research_providers import trusted_media_url
    identity=post_identity(url)
    if not identity or identity[0] not in ('Instagram','TikTok'):return {}
    platform,canonical=identity
    class PreviewParser(HTMLParser):
        image = ''
        video_detail = ''
        reading_video_detail = False

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == 'img' and 'EmbeddedMediaImage' in attributes.get('class', ''):
                self.image = attributes.get('src', '')
            if tag == 'meta' and attributes.get('property') == 'og:image' and not self.image:
                self.image = attributes.get('content', '')
            if tag == 'script' and attributes.get('id') == '__UNIVERSAL_DATA_FOR_REHYDRATION__':
                self.reading_video_detail = True

        def handle_data(self, data):
            if self.reading_video_detail:
                self.video_detail += data

        def handle_endtag(self, tag):
            if tag == 'script':
                self.reading_video_detail = False

        def tiktok_preview(self, post_id):
            if not self.video_detail:
                return '', False
            try:
                scope = json.loads(self.video_detail)['__DEFAULT_SCOPE__']
                detail = scope['webapp.video-detail']
                status = detail.get('statusMsg', '')
                if detail.get('statusCode') != 0:
                    flags = set(status.split(',')) if isinstance(status, str) else set()
                    return '', bool(flags & {'cross_border_violation', 'status_reviewing'})
                item = detail['itemInfo']['itemStruct']
                if str(item.get('id')) != post_id:
                    return '', False
                video = item['video']
                return trusted_media_url(video.get('cover') or '') or trusted_media_url(video.get('originCover') or ''), False
            except (KeyError, AttributeError, TypeError, ValueError):
                return '', False
    def bounded_text(client,target):
        with client.stream('GET',target) as response:
            if response.status_code!=200:return ''
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>750000:return ''
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8',errors='replace')
    try:
        video = ''
        unavailable = False
        with httpx.Client(timeout=4,follow_redirects=False) as client:
            if platform=='Instagram':
                raw = bounded_text(client, 'https://www.instagram.com'+urlsplit(canonical).path+'embed/')
                parser = PreviewParser()
                parser.feed(raw)
                image = parser.image
                # The public player can carry the signed video in escaped JSON.
                import html
                match = re.search(r'"video_url"\s*:\s*("(?:\\.|[^"\\])*")', html.unescape(raw).replace(r'\"', '"'))
                if match:
                    video = json.loads(match.group(1))
                    if video.startswith(r'https:\/'):
                        video = json.loads('"' + video + '"')
            else:
                # TikTok oEmbed rejects the otherwise valid non-www canonical
                # link. Keep stable source IDs, use the required host here.
                embed_original='https://www.tiktok.com'+urlsplit(canonical).path
                try:
                    raw = bounded_text(client, 'https://www.tiktok.com/oembed?url=' + quote(embed_original, safe=''))
                    image = trusted_media_url(json.loads(raw).get('thumbnail_url', '')) if raw else ''
                except (httpx.HTTPError, ValueError, AttributeError, TypeError):
                    image = ''
                if not image:
                    parser = PreviewParser()
                    parser.feed(bounded_text(client, embed_original))
                    post_id = urlsplit(canonical).path.rstrip('/').rsplit('/', 1)[-1]
                    cover, unavailable = parser.tiktok_preview(post_id)
                    image = cover or parser.image
        result = {'thumbnail': trusted_media_url(image), 'video': trusted_media_url(video)}
        if unavailable:
            result['unavailable'] = True
        return result
    except (httpx.HTTPError, ValueError, TypeError):return {}


def fetch_thumbnail(url):
    return fetch_post_preview(url).get('thumbnail', '')

