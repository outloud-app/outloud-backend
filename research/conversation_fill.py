"""Fill sparse conversation lanes with a different native query, under the same budget.

Never repeat a failed query, lower evidence standards, or substitute web search.
"""
import os


def fill(project, selected, quality, on_progress=None, *, brief=None):
    if os.environ.get('OUTLOUD_CONVERSATION_START_ALLOWED')!='1':
        return selected,quality,[],[]
    from native_conversations import queries_for,discover
    from native_access import NativeCapacityUnavailable
    from research_providers import evaluate
    from research_quality import is_recent_conversation, RELEASE_MINIMUM, select_results
    collections=[];issues=[]
    initial=max(1,min(3,int(os.environ.get('OUTLOUD_NATIVE_CONVERSATION_QUERY_LIMIT','1'))))
    def needs_more(platform):
        recent=[source for source in selected if is_recent_conversation(source)]
        platform_count=sum(source['platform']==platform for source in recent)
        minimum=RELEASE_MINIMUM['conversations']
        return platform_count==0 or (len(recent)<minimum and platform_count<(minimum+1)//2)

    for platform in ('X','Reddit'):
        if not needs_more(platform):continue
        try:
            plan=queries_for(project,platform)[:3]
            available=list(dict.fromkeys(plan[initial:]+scoped_queries(plan,brief,platform)))
        except Exception as error:
            collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':0,'status':'unavailable','error_type':type(error).__name__})
            issues.append(platform+' conversation planning could not finish.')
            continue
        from provider_budget import BudgetExceeded
        from native_conversations import ConversationUnavailable
        examined={source['id'] for source in selected}
        for query in available:
            if not needs_more(platform):break
            try:
                rows=discover(query,20,90,platform)
                collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':len(rows),'status':'completed'})
                pending=[s for s in rows if s['id'] not in examined]
                if not pending:continue
                verdicts=evaluate(project,pending)
                examined.update(verdicts)
                checked=[{**s,'evaluation':verdicts[s['id']]} for s in pending if s['id'] in verdicts]
                previous_rejections=quality.get('rejected',[])
                selected,quality=select_results(project,selected+checked,require_evaluation=True,native_only=True)
                quality['rejected']=previous_rejections+quality.get('rejected',[])
                if on_progress:on_progress({'stage':'evaluating','discover':[s for s in selected if s['section']=='discover'],
                                            'conversations':[s for s in selected if s['section']=='conversations']})
            except Exception as error:
                collections.append({'platform':platform,'lane':'conversations','phase':'fill','returned':0,'status':'unavailable','error_type':type(error).__name__})
                issues.append(platform+' conversation expansion could not finish; existing checked results were kept.')
                if isinstance(error,NativeCapacityUnavailable):return selected,quality,collections,issues
                if isinstance(error,(BudgetExceeded,ConversationUnavailable)):break
    return selected,quality,collections,issues


def scoped_queries(plan,brief,platform):
    """Use native community or exact-task search when the broad pass is sparse."""
    import re
    if not brief or not plan or not plan[0].endswith(' help'):
        return []
    task=plan[0].removesuffix(' help')
    if not re.fullmatch(r"[\w '-]{3,80}",task):
        return []
    if platform=='X':
        return [f'"{task}" ("looking for" OR "does anyone" OR "is there")',
                f'"{task}" ("takes too long" OR "frustrating" OR "I wish")']
    communities=[name for name in brief.get('subreddits',[]) if re.fullmatch(r'[A-Za-z0-9_]{2,40}',name)]
    return [f'subreddit:{name} self:true "{task}"' for name in communities[:3]]
