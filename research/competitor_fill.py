"""Expand sparse competitor feeds using names grounded in checked publisher posts."""
import os

from research_quality import RELEASE_MINIMUM, select_results


def discovered_competitors(project, sources):
    """Original, checked posts can identify a brand before ownership is resolved."""
    from competitor_accounts import brand
    from research_quality import is_native_source

    names={}
    for source in sources:
        decision=source.get('evaluation') or {}
        name=decision.get('competitor_name')
        claim=decision.get('competitor_job_quote')
        original=source.get('title','')+' '+source.get('summary','')
        if (is_native_source(source) and decision.get('provider')=='gemini'
            and decision.get('intent')=='competitor' and decision.get('relevance',0)>=.65
            and isinstance(name,str) and 2<=len(name.strip())<=70
            and isinstance(claim,str) and len(claim)>=12 and claim in original
            and brand(name)!=brand(project.name)):
            names.setdefault(brand(name),name.strip())
    return list(names.values())[:3]


def fill(project, selected, quality, *, checked_sources=(), evaluation_failures=None):
    if (os.environ.get('OUTLOUD_MEDIA_SEARCH_ALLOWED')!='1'
            or os.environ.get('OUTLOUD_MEDIA_START_ALLOWED')!='1'
            or quality['lane_counts']['competitors']>=RELEASE_MINIMUM['competitors']):
        return selected,quality,[]
    from native_collection import phrase
    from research_providers import discover_native_media, evaluate
    from provider_budget import BudgetExceeded
    from native_access import NativeCapacityUnavailable

    names=[]
    for source in selected:
        if source['intent']!='competitors' or not source.get('publisher_basis'):continue
        name=phrase((source.get('evaluation') or {}).get('competitor_name',''))
        if name and name.casefold()!=project.name.casefold() and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)

    counts=[]
    examined={source['id'] for source in selected}
    suggested=discovered_competitors(project,checked_sources)
    if suggested:
        from competitor_accounts import collect_for_project
        rows,report=collect_for_project(project,suggestions=suggested)
        counts.append({'platform':'native','lane':'competitors','phase':'discovered_publishers',
                       'status':'completed','returned':len(rows),'accounts_verified':report['accounts_verified']})
        candidates=[source for source in rows if source['id'] not in examined][:60]
        if candidates:
            try:
                decisions=evaluate(project,candidates)
            except (BudgetExceeded,RuntimeError,ValueError):
                decisions={}
            if evaluation_failures is not None:evaluation_failures.extend(getattr(decisions,'failure_reasons',[]))
            examined.update(decisions)
            checked=[{**source,'evaluation':decisions[source['id']]} for source in candidates if source['id'] in decisions]
            prior=quality['rejected']
            selected,quality=select_results(project,selected+checked,require_evaluation=True,native_only=True)
            quality['rejected']=prior+quality['rejected']
    for platform in ('TikTok','Instagram'):
        for name in names[:2]:
            if quality['lane_counts']['competitors']>=RELEASE_MINIMUM['competitors']:
                return selected,quality,counts
            details={'platform':platform,'lane':'competitors','phase':'publisher_fill'}
            try:
                query=phrase(name+' product',instagram=platform=='Instagram')
                rows=discover_native_media([query],20,90,platform,platform=='Instagram')
                counts.append({**details,'returned':len(rows),'status':'completed'})
                candidates=[source for source in rows if source['id'] not in examined]
                if not candidates:continue
                decisions=evaluate(project,candidates)
                if evaluation_failures is not None:evaluation_failures.extend(getattr(decisions,'failure_reasons',[]))
                examined.update(decisions)
                checked=[{**source,'evaluation':decisions[source['id']]} for source in candidates if source['id'] in decisions]
                prior=quality['rejected']
                selected,quality=select_results(project,selected+checked,require_evaluation=True,native_only=True)
                quality['rejected']=prior+quality['rejected']
            except Exception as error:
                counts.append({**details,'returned':0,'status':'unavailable','error_type':type(error).__name__})
                if isinstance(error,(BudgetExceeded,NativeCapacityUnavailable)):return selected,quality,counts
    return selected,quality,counts
