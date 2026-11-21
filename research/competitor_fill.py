"""Expand sparse competitor feeds using names grounded in checked publisher posts."""
import os

from research_quality import RELEASE_MINIMUM, select_results


def fill(project, selected, quality):
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
                examined.update(decisions)
                checked=[{**source,'evaluation':decisions[source['id']]} for source in candidates if source['id'] in decisions]
                prior=quality['rejected']
                selected,quality=select_results(project,selected+checked,require_evaluation=True,native_only=True)
                quality['rejected']=prior+quality['rejected']
            except Exception as error:
                counts.append({**details,'returned':0,'status':'unavailable','error_type':type(error).__name__})
                if isinstance(error,(BudgetExceeded,NativeCapacityUnavailable)):return selected,quality,counts
    return selected,quality,counts
