"""Evidence-based result routing and launch checks, shared by retrieval and refresh."""
import math
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from product_profile import clean, terms

QUALITY_VERSION=22
# Independent initial workspace targets. One busy lane cannot consume another's
# capacity; these bound publication, not the reusable source corpus.
LANE_LIMITS={'discover':25,'competitors':15,'conversations':20}
MAX_RESULTS=sum(LANE_LIMITS.values())
CONVERSATION_DAYS=30
RECENT_CONVERSATION_DAYS=7
RELEASE_MINIMUM={'discover':15,'competitors':15,'conversations':15}
MIN_DISCOVERY_VIDEO_VIEWS=1_000


def is_recent_conversation(source, now=None):
    if source.get('intent') != 'conversations':
        return False
    try:
        published=datetime.fromisoformat(source['published_at'].replace('Z','+00:00'))
        age=(now or datetime.now(timezone.utc))-published
        return timedelta(0)<=age<=timedelta(days=RECENT_CONVERSATION_DAYS)
    except (KeyError, AttributeError, ValueError, TypeError):
        return False


def route_source(source):
    text=(source.get('title','')+' '+source.get('summary','')).strip()
    builder=re.search(r"\b(?:i|we)\s+(?:(?:have|recently|just|finally)\s+)*(?:built|made|created|launched|developed)\b|\b(?:i['’]ve|we['’]ve)\s+(?:built|made|created|launched)\b|\bbuilt\s+(?:a|an|my|our)\b",text,re.I)
    product_pitch=re.search(r"\b(?:our|my)\s+(?:app|platform|software|scanner|service|tool)\b|\bno.code platform\b|\b(?:try|download|sign up for|introducing)\s+(?:our|my|the)\b",text,re.I)
    software_build=builder and re.search(r'\b(?:app|platform|software|scanner|service|tool|bot|extension|website|agent|system)\b',text[builder.start():builder.end()+100],re.I)
    if software_build or product_pitch:return 'competitors'
    if source['platform'] not in ('Reddit','X'):return 'discover'
    # Pain described in an industry essay is not necessarily the author's
    # present unmet need. Do not turn marketing/editorial framing into a lead.
    asks_for_help=re.search(r"\b(?:looking for|is there|does anyone|can anyone|recommend(?:ations)?|any (?:service|tool|app))\b",text,re.I)
    editorial=re.search(r"\b(?:studies show|the data:|what institutional traders do|the shift happening|simple formula:)\b",text,re.I)
    used_solution=re.search(r"\b(?:alert pinged|my bot (?:caught|found|notified)|my scanner (?:caught|found)|now (?:it|the bot) alerts me)\b",text,re.I)
    if (editorial or used_solution) and not asks_for_help:return 'reject'
    # A success story followed by a broad question is not an unresolved buying need.
    resolved=re.search(r"\b(?:finally set up|problem (?:is )?solved|(?:honestly )?saved my (?:sleep|time|sanity)|works perfectly|no longer (?:need|have) to|replaced my .{0,35} with|no sleepless nights|getting back to actually living|(?:found|finding) (?:a solution|peace|something that works))\b",text,re.I)
    unresolved=re.search(r"\b(?:still (?:missing|struggling|looking|need|can't|cannot)|looking for alternatives|(?:anything|something) better|doesn't work|does not work|not working|any better (?:tools|options|alternatives))\b",text,re.I)
    if resolved and not unresolved:return 'reject'
    if unresolved:return 'conversations'
    request=re.search(r"\b(?:looking for|any (?:service|tool|app)|is there|does anyone|has anyone|how do (?:you|i)|what (?:do you|helps|tools)|what['’]s (?:your|the best)|how (?:can|should|would) (?:i|we)|should (?:i|we)|recommend|need (?:a|an|to)|anyone else)\b",text,re.I)
    # Natural frustration is not restricted to the original chart-watching
    # vocabulary. These still require product-specific semantic validation.
    pain=re.search(r"\b(?:i|my|we)\b.{0,100}\b(?:missing|missed|struggling|struggle|waste|wasting|tired|hate|frustrated|frustrating|annoyed|discouraged|overwhelmed|exhausted|confused|can't|cannot|couldn't|takes forever|too long|keep|need)\b",text,re.I)
    # Conversational requests need not use formal "recommend an app" wording.
    natural_request=re.search(r"\b(?:any (?:tips|ideas|suggestions|advice)|what should (?:i|we)|how to (?:start|keep|stop|manage|remember)|wish (?:i|we) could)\b",text,re.I)
    natural_burden=re.search(r"(?:^|[.!?]\s+)(?:struggling (?:with|to)|can['’]t seem to|cannot seem to)\b",text,re.I)
    # Social posts often omit "I". An explicit ongoing burden still counts;
    # this is not a licence to classify every mention of an activity as pain.
    implicit_burden=re.search(r"(?:^|[.!?]\s+)(?:been|spending|wasting)\b.{0,100}\b(?:too long|too much|forever|exhausting|overwhelming)\b",text,re.I)
    return 'conversations' if request or pain or implicit_burden or natural_request or natural_burden else 'reject'


def measured_metric(metrics, key):
    value=metrics.get(key)
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None


def retrieved_video_views(source):
    metrics=source.get('metrics') or {}
    if not metrics.get('provider') or not metrics.get('checked_at'):
        return None
    views=measured_metric(metrics,'views')
    return measured_metric(metrics,'plays') if views is None else views


def attention(source):
    metrics=source.get('metrics') or {}
    # Numbers are accepted only with retrieval provenance; index prose is not a metric API.
    if not metrics.get('provider') or not metrics.get('checked_at'):
        return {'status':'unverified','score':0,'reason':'Post performance has not been retrieved.'}
    def number(key):return measured_metric(metrics,key)
    views,likes,comments=retrieved_video_views(source),number('likes'),number('comments')
    if views is None and likes is None and comments is None and number('score') is None:return {'status':'unavailable','score':0,'reason':'The source did not expose engagement counts.'}
    from research_retrieval import relative_attention
    relative=relative_attention(source)
    if relative.get('status')=='measured' or relative.get('growth_ratio') is not None:
        ratio=max(relative.get('ratio',0),relative.get('growth_ratio',0))
        return {'status':'qualified' if ratio>=1.5 else 'below_threshold','score':round(math.log1p(ratio)*8,2),'reason':relative['reason'],'relative':relative}
    # Without a cohort we can show measured attention, but cannot call it an
    # outperformer. Raw counts rank these candidates rather than hard excluding niches.
    measured=any(value is not None and value>0 for value in (views,likes,comments,number('score')))
    return {'status':'measured' if measured else 'below_threshold',
            'score':round(math.log1p(views or 0)+math.log1p(likes or 0)*.6+math.log1p(comments or 0)*.4,2),
            'reason':'Retrieved engagement; comparative performance is not established yet.' if measured else 'No positive engagement was retrieved.',
            'relative':relative}



def evidence_notes(source,project):
    sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',source.get('summary','')) if len(s.strip())>25]
    problem=terms(project.problem or project.description)
    quote=max(sentences,key=lambda s:len(terms(s)&problem),default='')
    return {'basis':'source_excerpt','problem_quote':quote,'product_problem':project.problem or project.description,
            'caption':source.get('summary',''),'transcript':None,'frames':[],
            'limitations':['No video transcript or frame analysis has been retrieved.'] if source.get('kind')=='Video' else []}


def matched_topics(project, source, evaluation):
    """Tag already-qualified originals with literal or independently checked topic evidence."""
    original = source.get('title', '') + ' ' + source.get('summary', '')
    words = set(re.findall(r"\b\w+\b", original.casefold()))
    evidence = evaluation.get('topic_evidence', [])
    output = []
    for keyword in getattr(project, 'keywords', []):
        tokens = set(re.findall(r"\b\w+\b", keyword.casefold()))
        quoted = isinstance(evidence, list) and any(
            isinstance(item, dict) and str(item.get('keyword', '')).casefold() == keyword.casefold()
            and isinstance(item.get('quote'), str) and len(item['quote']) >= 12
            and item['quote'] in original for item in evidence
        )
        if (tokens and tokens <= words) or quoted:
            output.append(keyword)
    return output


def is_native_source(source):
    return (source.get('evidence') or {}).get('type') == 'original_platform_post'


def select_results(project,candidates,require_evaluation=False,native_only=False):
    accepted={};rejections=[]
    for original in candidates:
        source=dict(original)
        if native_only and not is_native_source(source):
            rejections.append({'id':source['id'],'reason':'Native collection requires an original platform record.'})
            continue
        evaluation=source.get('evaluation') or {}
        if evaluation.get('provider')=='gemini' and evaluation.get('checked_at') and evaluation.get('intent')=='irrelevant':
            rejections.append({'id':source['id'],'reason':'Semantic evaluation rejected the problem match.'})
            continue
        editorial = (
            evaluation.get('provider') == 'local_editorial_review'
            and (
                evaluation.get('intent') == 'competitor'
                or (evaluation.get('intent') == 'audience_problem'
                    and evaluation.get('need_type') in ('workflow_friction', 'niche_question'))
            )
            and source.get('platform') in ('Reddit', 'X')
            and (source.get('evidence') or {}).get('type') == 'original_platform_post'
        )
        verified=((evaluation.get('provider')=='gemini' or editorial) and evaluation.get('checked_at')
                  and isinstance(evaluation.get('evidence_quote'),str)
                  and len(evaluation['evidence_quote'])>=12
                  and evaluation['evidence_quote'] in source.get('title','')+' '+source.get('summary',''))
        if (native_only or require_evaluation) and not verified:
            rejections.append({'id':source['id'],'reason':'Semantic evaluation is required but absent.'});continue
        if verified:
            confidence=evaluation.get('relevance',0)
            if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not math.isfinite(confidence) or confidence<.5 or confidence>1 or evaluation.get('intent')=='irrelevant':
                rejections.append({'id':source['id'],'reason':'Semantic evaluation rejected the problem match.',
                                   'evaluation':{key:evaluation[key] for key in ('intent','relevance','reason','evidence_quote') if key in evaluation}});continue
            lane={'audience_problem':'conversations','competitor':'competitors','creative_reference':'discover'}.get(evaluation.get('intent'),'reject')
            if lane=='conversations' and source['platform'] not in ('Reddit','X'):lane='discover'
        else:
            lane=route_source(source)
        # A model cannot move a builder's product pitch into audience leads or
        # For You. Product promotion belongs in the competitor lane, even when
        # it describes the same pain as our user's product.
        if route_source(source)=='competitors':
            if verified and lane!='competitors':
                rejections.append({'id':source['id'],'reason':'Builder wording alone does not establish a same-job competitor.'});continue
            lane='competitors'
        # Conversations also contains relevant research questions, not only
        # prospective buyers. Preserve the distinction in the published signal.
        niche_question=evaluation.get('request_quote') if editorial and evaluation.get('need_type')=='niche_question' else None
        if verified and lane=='discover' and source['platform'] in ('Reddit','X') and evaluation.get('relevance',0)>=.75 and route_source(source)=='conversations':
            original_text=source.get('title','')+' '+source.get('summary','')
            for sentence in re.split(r'(?<=[.!?])\s+',original_text):
                if 12<=len(sentence.strip())<=400 and '?' in sentence and re.search(r"\b(?:how (?:do|can|should) (?:i|we|you)|does anyone|can anyone|what (?:do you|tools|helps)|which .{0,50}(?:use|recommend))\b",sentence,re.I):
                    niche_question=sentence.strip();lane='conversations';break
        publisher_basis=None
        if lane=='competitors' and verified and ('policy_version' in evaluation or editorial):
            original=source.get('title','')+' '+source.get('summary','')
            quote=evaluation.get('competitor_publisher_quote','')
            job=evaluation.get('competitor_job_quote','')
            name=evaluation.get('competitor_name','')
            named_job=isinstance(name,str) and bool(name.strip()) and isinstance(job,str) and len(job)>=12 and job in original
            quoted_publisher=isinstance(quote,str) and len(quote)>=12 and quote in original
            maker_pattern = (
                r"\b(?:our|my)\s+(?:app|product|software|platform|tool|scanner)"
                r"|\b(?:i|we)\s+(?:(?:just|have|recently)\s+)*(?:built|made|created|launched|developed)"
                r"|\b(?:i(?:['’]m|\s+am)|we(?:['’]re|\s+are)|(?:i|we)(?:['’]ve|\s+have)\s+been)"
                r"\s+(?:building|developing|working\s+on)"
                r"|\b(?:founder|cofounder|co-founder|creator|developer)\b"
            )
            maker=quoted_publisher and re.search(maker_pattern,quote,re.I)
            def identity(value):
                value=re.sub(r'[^a-z0-9]','',str(value).casefold())
                return re.sub(r'(?:official|app)$','',value)
            account_match=(len(identity(name))>=4 and identity(name)==identity(source.get('author',''))
                           and (source.get('evidence') or {}).get('type')=='original_platform_post')
            brand_voice=quoted_publisher and (
                re.search(r"\b(?:our|my|we|us)\b",quote,re.I) or identity(name) in identity(quote)
            )
            if named_job and (maker or (account_match and brand_voice)):
                publisher_basis='maker_quote' if maker else 'matching_account_and_brand_voice'
            elif named_job and source['platform'] in ('Instagram','TikTok') and source.get('kind') in ('Video','Image') and not re.search(maker_pattern,original,re.I) and not account_match:
                # A creator's relevant review/demo is creative inspiration. A lack
                # of first-party ownership is not evidence that its topic is bad.
                # Do not turn it into a competitor-owned post or a buying lead.
                lane='discover'
                source['match_reason']='A product demonstration in your niche: “'+job[:180]+'”'
                publisher_basis='third_party_demonstration'
            else:
                rejections.append({'id':source['id'],'reason':'Competitors requires evidenced first-party publication and a competing product; reviews are excluded.'});continue
        # Resolved stories cannot become leads because the model mistakes a
        # closing discussion question for an unmet need.
        if lane=='conversations' and not editorial and route_source(source)=='reject':
            rejections.append({'id':source['id'],'reason':'No current unresolved audience need is evidenced.'});continue
        education=re.search(r'\b(?:masterclass|webinar|tutorial|lesson|course for beginners)\b',source.get('title',''),re.I)
        learning_problem=re.search(r'\b(?:learn|learning|teach|teaching|study|studying|education)\b',project.problem or project.description,re.I)
        if not verified and education and not learning_problem:
            rejections.append({'id':source['id'],'reason':'Broad educational content is not evidence of the product problem.'});continue
        if lane=='reject':rejections.append({'id':source['id'],'reason':'No audience problem or request evidenced.'});continue
        request_quote=niche_question or evaluation.get('request_quote','')
        verified_need=(verified and (niche_question is not None or evaluation.get('need_status')=='unresolved') and isinstance(request_quote,str) and len(request_quote)>=12 and request_quote in source.get('title','')+' '+source.get('summary',''))
        if lane=='conversations' and ((verified and not verified_need) or (not verified and route_source(source)=='reject')):
            rejections.append({'id':source['id'],'reason':'No unresolved audience need is evidenced.'});continue
        if lane=='conversations' and verified and not niche_question and evaluation.get('policy_version',0)>=15 and evaluation.get('need_type') not in ('software_recommendation','workflow_friction','feature_request'):
            rejections.append({'id':source['id'],'reason':'Conversations requires an addressable software or workflow need; general outcome advice is excluded.'});continue
        if lane=='conversations' and verified and evaluation.get('policy_version',0)>=15 and evaluation.get('need_type')=='software_recommendation':
            software_request=re.search(r"\b(?:apps?|software|tools?|trackers?|loggers?|scanners?|dashboards?|extensions?|apis?|bots?|scripts?|plugins?)\b",request_quote,re.I)
            named_alternative=any(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',request_quote,re.I)
                                  for name in getattr(project,'competitors',[]) if isinstance(name,str) and len(name.strip())>=3)
            if not software_request and not named_alternative:
                rejections.append({'id':source['id'],'reason':'The quoted recommendation request does not identify a tool or competing product.'});continue
        # A broader lifestyle interest is useful inspiration at most, not a
        # prospective customer asking for help with this product's job.
        if lane=='conversations' and verified and evaluation.get('relevance',0)<.65:
            rejections.append({'id':source['id'],'reason':'The request concerns a different task; broad audience overlap is not a lead.'});continue
        if lane=='conversations' and verified and not editorial and route_source({'platform':source['platform'],'title':'','summary':request_quote})!='conversations':
            rejections.append({'id':source['id'],'reason':'The quoted evidence is not itself an unresolved request or frustration.'});continue
        if lane=='discover' and source['platform'] not in ('Instagram','TikTok'):
            rejections.append({'id':source['id'],'reason':'For You contains native short-form media; text posts belong in Conversations only when an actual need is evidenced.'});continue
        if lane=='discover' and verified and evaluation.get('relevance',0)<.65:
            rejections.append({'id':source['id'],'reason':'A shared broad theme is insufficient; creative references need a concrete niche connection.'});continue
        if (native_only or require_evaluation) and lane in ('discover','competitors') and str(source.get('kind')).casefold()=='video':
            views=retrieved_video_views(source)
            if views is None or views<MIN_DISCOVERY_VIDEO_VIEWS:
                rejections.append({'id':source['id'],'reason':'Discover videos require at least 1,000 measured views or plays.'});continue
        source['match_level']=('Direct' if evaluation.get('relevance',0)>=.85 else 'Adjacent' if evaluation.get('relevance',0)>=.65 else 'Related') if verified else 'Related'
        if publisher_basis!='third_party_demonstration':source['match_reason']=evaluation.get('reason','')
        if publisher_basis:source['publisher_basis']=publisher_basis
        source['matched_terms'] = list(dict.fromkeys([*(source.get('matched_terms') or []), *matched_topics(project, source, evaluation if verified else {})]))
        source['semantic_verified']=bool(verified)
        source['competitor']=lane=='competitors'
        source['section']='conversations' if lane=='conversations' else 'discover'
        source['intent']=lane
        source['attention']=attention(source)
        if (native_only or require_evaluation) and lane=='discover' and source['attention']['status'] not in ('qualified','measured'):
            rejections.append({'id':source['id'],'reason':'For You requires a semantic audience connection and retrieved engagement.'});continue
        source['analysis']=source.get('analysis') or evidence_notes(source,project)
        if lane=='conversations':
            sentences=re.split(r'(?<=[.!?])\s+',source.get('summary',''))
            explicit=next((sentence.strip() for sentence in sentences if re.search(r'\b(?:looking for|need (?:a|an|something)|does anyone|is there|can anyone|how do (?:you|i)|recommend)\b',sentence,re.I)),None)
            quote=request_quote if verified_need else explicit or source['analysis'].get('problem_quote')
            if quote and len(quote)>320:quote=quote[:320].rsplit(' ',1)[0]
            # A verified frustration is useful without pretending its author
            # asked for a recommendation. The quoted text decides the signal.
            if verified_need:
                explicit=bool(re.search(r"\b(?:looking for|need (?:a|an|something)|does anyone|is there|can anyone|how (?:do|can|should) (?:you|i|we)|should (?:i|we)|recommend)\b",request_quote,re.I))
            source['conversation_signal']={'type':'question' if niche_question else 'request' if explicit else 'problem','quote':quote or ''}
            source['match_reason']=('A question about your niche: “'+quote+'”') if niche_question else ('They are asking for a solution: “'+quote+'”') if explicit else ('They describe this problem: “'+quote+'”' if quote else '')
        specific=len(source.get('matched_terms',[]))
        published=source.get('published_at')
        try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(published.replace('Z','+00:00'))).days if published else None
        except (ValueError,TypeError):age=None
        if age is not None and (age>365 or age < -2):
            rejections.append({'id':source['id'],'reason':'Publication date is outside the supported discovery window.'});continue
        if lane=='conversations' and (age is None or age>CONVERSATION_DAYS):
            rejections.append({'id':source['id'],'reason':'Audience conversations require a verified publication date within the last 30 days.'})
            continue
        # Conversation urgency is independent of popularity. Discovery retains
        # established creatives for a year; fresh discussions get priority.
        freshness=(12 if age is not None and age<=7 else 4) if lane=='conversations' else (4 if age is not None and age<=90 else 0)
        source['_score']=source.get('_score',specific)+(8 if source.get('conversation_signal',{}).get('type')=='request' else 0)+source['attention']['score']+freshness
        # Preserve the richer version of the same original post.
        old=accepted.get(source['url'])
        if not old or source['_score']>old['_score'] or source.get('metrics'):accepted[source['url']]=source
    ranked=[];seen_posts={}
    for source in sorted(accepted.values(),key=lambda s:-s['_score']):
        # Same author's verbatim cross-post is one reference, even when the
        # platform gave each community submission a different permalink.
        body=re.sub(r'\s+',' ',source.get('summary','')).strip().casefold()
        author=str(source.get('author','')).strip().casefold()
        identity=(source['platform'],author)
        previous=seen_posts.get(identity,[]) if author else []
        if len(body)>=120 and any(body==prior or SequenceMatcher(None,body,prior,autojunk=False).ratio()>=.90 for prior in previous):
            rejections.append({'id':source['id'],'reason':'Duplicate author cross-post.'});continue
        if len(body)>=120 and author:seen_posts.setdefault(identity,[]).append(body)
        ranked.append(source)
    chosen=[]
    # Keep independent capacities and source diversity within each lane.
    for lane in ('conversations','discover','competitors'):
        pool=[s for s in ranked if s['intent']==lane]
        if lane == 'conversations':
            pool.sort(key=lambda source: source.get('published_at') or '', reverse=True)
        diverse=[]
        seen=set()
        for source in pool:
            if source['platform'] not in seen:
                diverse.append(source);seen.add(source['platform'])
        diverse.extend(s for s in pool if s not in diverse)
        chosen.extend(diverse[:LANE_LIMITS[lane]])
    for source in chosen:source.pop('_score',None)
    verified=sum(s['intent']=='discover' and s['attention']['status']=='qualified' for s in chosen)
    report={'version':QUALITY_VERSION,'candidates':len(candidates),'accepted':len(chosen),'rejected':rejections,'verified_discovery':verified,'measured_discovery':sum(s['intent']=='discover' and s['attention']['status'] in ('qualified','measured') for s in chosen),
      'launch_ready':bool(verified and any(s['intent']=='conversations' for s in chosen)),
      'blockers':[] if verified else ['No problem-matched social posts with qualifying measured engagement yet.']}
    # A single good post is not proof of a useful three-tab demo. Require a
    # usable visible selection in each lane, real media, and both lead sources.
    lane_counts={lane:sum(s['intent']==lane for s in chosen) for lane in ('discover','competitors','conversations')}
    report['lane_counts']=lane_counts
    now=datetime.now(timezone.utc)
    recent_conversations=[source for source in chosen if is_recent_conversation(source,now)]
    report['release_minimum']=dict(RELEASE_MINIMUM)
    report['recent_conversation_count']=len(recent_conversations)
    for lane,minimum in RELEASE_MINIMUM.items():
        count=len(recent_conversations) if lane=='conversations' else lane_counts[lane]
        if count<minimum:
            report['launch_ready']=False
            label='Conversations from the past week' if lane=='conversations' else lane.capitalize()
            report['blockers'].append(f'{label}: {count} checked results; launch requires {minimum}.')
    media_platforms=set()
    for source in chosen:
        media=source.get('media') or {}
        if source['intent']=='discover' and source['platform'] in ('TikTok','Instagram') and (media.get('poster') or (media.get('type')=='image' and media.get('url'))):
            media_platforms.add(source['platform'])
    if len(media_platforms)<2:
        report['launch_ready']=False
        report['blockers'].append('For You needs checked Instagram and TikTok media previews.')
    conversation_platforms={s['platform'] for s in recent_conversations}
    if not {'Reddit','X'}<=conversation_platforms:
        report['launch_ready']=False
        report['blockers'].append('Current audience requests from both Reddit and X have not been established.')
    semantic=sum(s.get('semantic_verified',False) for s in chosen)
    if not any(s['intent']=='conversations' for s in chosen):
        report['blockers'].append('No current unresolved audience request passed the checks yet.')
    report['semantically_evaluated']=semantic
    if semantic!=len(chosen) or not chosen:
        report['launch_ready']=False
        report['blockers'].append('Selected results have not all passed semantic evaluation.')
    return chosen,report
