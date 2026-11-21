"""Fill sparse conversation lanes with a different native query, under the same budget.

Never repeat a failed query, lower evidence standards, or substitute web search.
"""
import os
from datetime import datetime, timedelta, timezone


def fill(project, selected, quality, on_progress=None, *, brief=None, observed=None, evaluation_failures=None):
    if os.environ.get('OUTLOUD_CONVERSATION_START_ALLOWED')!='1':
        return selected,quality,[],[]
    from native_conversations import ConversationUnavailable,queries_for,discover,discover_replies,initial_query_limit,candidate_limit
    from native_access import NativeCapacityUnavailable
    from research_providers import evaluate
    from research_quality import MIN_CONVERSATIONS_PER_PLATFORM, select_results
    collections=[];issues=[]
    initial=initial_query_limit()
    def needs_more(platform):
        return sum(source.get('intent')=='conversations' and source['platform']==platform
                   for source in selected)<MIN_CONVERSATIONS_PER_PLATFORM

    for platform in ('X','Reddit'):
        if not needs_more(platform):continue
        use_fallback=platform=='X' and (bool(brief) or callable(getattr(project,'model_dump',None))) and os.environ.get('OUTLOUD_X_COLLECTOR')!='xquik'
        try:
            try:
                plan=queries_for(project,platform)[:3]
            except ConversationUnavailable:
                if not use_fallback:raise
                plan=queries_for(project,platform,x_adapter='xquik')[:3]
                available=[]
            else:
                available=list(dict.fromkeys(plan[initial:]+scoped_queries(plan,brief,platform)))
        except Exception as error:
            collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':0,'status':'unavailable','error_type':type(error).__name__})
            issues.append(platform+' conversation planning could not finish.')
            plan=[]
            available=[]
        from provider_budget import BudgetExceeded
        examined={source['id'] for source in selected}
        targets=[]
        if use_fallback:
            # The initial pass already queried the primary adapter.
            targets.extend((query,'xquik') for query in alternate_x_queries(project,plan,brief))
        if platform=='X' and (selected or observed):
            targets.extend((url,'thread') for url in thread_seeds(project,selected,observed or []))
        targets.extend((query,'search') for query in available)
        unavailable=set()
        for target,method in targets:
            if not needs_more(platform):break
            if method in unavailable:continue
            if method=='thread':
                details={'seed_url':target}
            else:
                details={'query':target}
                if method=='xquik':details['collector']='xquik'
            try:
                if method=='thread':
                    rows=discover_replies(target,20,20)
                elif method=='xquik':
                    rows=discover(target,candidate_limit(platform,x_adapter='xquik'),45,platform,x_adapter='xquik')
                else:
                    rows=discover(target,candidate_limit(platform),90,platform)
                if observed is not None:observed.extend(rows)
                collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':len(rows),'status':'completed',
                                    **details,'source_ids':[source['id'] for source in rows]})
                pending=[s for s in rows if s['id'] not in examined]
                if not pending:continue
                verdicts=evaluate(project,pending)
                if evaluation_failures is not None:evaluation_failures.extend(getattr(verdicts,'failure_reasons',[]))
                examined.update(verdicts)
                checked=[{**s,'evaluation':verdicts[s['id']]} for s in pending if s['id'] in verdicts]
                previous_rejections=quality.get('rejected',[])
                selected,quality=select_results(project,selected+checked,require_evaluation=True,native_only=True)
                quality['rejected']=previous_rejections+quality.get('rejected',[])
                if on_progress:on_progress({'stage':'evaluating','discover':[s for s in selected if s['section']=='discover'],
                                            'conversations':[s for s in selected if s['section']=='conversations']})
            except Exception as error:
                collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':0,'status':'unavailable','error_type':type(error).__name__,**details})
                issues.append(platform+' conversation expansion could not finish; existing checked results were kept.')
                if isinstance(error,NativeCapacityUnavailable):return selected,quality,collections,issues
                if isinstance(error,BudgetExceeded):break
                if isinstance(error,ConversationUnavailable):unavailable.add(method)
    return selected,quality,collections,issues


def alternate_x_queries(project,plan,brief):
    from native_collection import activity_phrases
    import re
    seeds=[query for query in plan if re.fullmatch(r"[\w '-]{3,80}",query)]
    seeds=list(dict.fromkeys([*seeds,*activity_phrases(project,brief)]))
    if not seeds or not callable(getattr(project,'model_dump',None)):return plan[:2]
    # Try distinct customer vocabulary and an earlier part of the same 30-day window.
    cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).date().isoformat()
    return [*seeds[:2],f'"{seeds[0]}" until:{cutoff}']


def scoped_queries(plan,brief,platform):
    """Use native community or exact-task search when the broad pass is sparse."""
    import re
    if not brief or not plan:
        return []
    tasks=[task for value in plan if re.fullmatch(r"[\w '-]{3,80}",task:=value.removesuffix(' help'))]
    if not tasks:return []
    if platform=='X':
        intents=('("looking for" OR "does anyone" OR "is there")',
                 '("takes too long" OR "frustrating" OR "I wish")')
        focused=[f'"{task}" {intent}' for task,intent in zip(tasks,intents)]
        # Exact phrases and mandatory intent language can return empty datasets.
        # Let the independent assessment identify useful requests after collection.
        plain=[task+' help' for task in tasks[:3]]
        return list(dict.fromkeys(plain+focused))
    communities=[name for name in brief.get('subreddits',[]) if re.fullmatch(r'[A-Za-z0-9_]{2,40}',name)]
    scoped=[(name,tasks[index%len(tasks)]) for index,name in enumerate(communities[:3])]
    return [f'subreddit:{name} self:true {task}' for name,task in scoped]+[
        f'subreddit:{name} self:true "{task}"' for name,task in scoped]

def thread_seeds(project,selected,observed):
    """Use recent native posts about the product's job as reply starting points."""
    from live_discovery import post_identity, publication
    from product_profile import research_context, terms
    from research_quality import CONVERSATION_DAYS, is_native_source, measured_metric

    candidates=[source for source in [*observed,*selected]
                if source.get('platform')=='X' and is_native_source(source)]
    if not candidates:return []
    context=research_context(project)
    job=terms(' '.join(str(context.get(key,'')) for key in ('product_job','customer_problem')))
    matched={}
    accepted={source['id'] for source in selected if source.get('intent')=='conversations'}
    for source in candidates:
        identity=post_identity(source.get('url'))
        _,age=publication(source.get('published_at'))
        replies=measured_metric(source.get('metrics') or {},'comments') or 0
        overlap=job&terms(source.get('title','')+' '+source.get('summary',''))
        if not identity or age is None or not 0<=age<=CONVERSATION_DAYS or replies<3 or len(overlap)<2:
            continue
        score=(source['id'] in accepted,len(overlap),min(replies,30),-age)
        if identity[1] not in matched or score>matched[identity[1]]:
            matched[identity[1]]=score
    return sorted(matched,key=matched.get,reverse=True)[:4]
