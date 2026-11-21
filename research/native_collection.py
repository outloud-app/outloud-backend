"""Product-independent native collection plans. No network or category templates."""
import re
from urllib.parse import urlsplit


def phrase(value, *, instagram=False):
    value=re.sub(r'https?://\S+|\b(?:site|after|before):\S+', '', str(value), flags=re.I)
    value=' '.join(re.findall(r'[\w-]+',value)[:8])[:120]
    if instagram and len(value.split())==1:value+=' ideas'
    return value if len(value)>=4 else ''


def activity_phrases(project, model=None):
    """Short search seeds from the user's topics and checked product plan."""
    model=model or {}
    values=[*getattr(project,'keywords',[]),*model.get('adjacent_topics',[])]
    for field in ('product_job','description','problem'):
        words=re.findall(r"[\w'-]+",str(getattr(project,field,'')))
        values.extend(' '.join(words[index:index+3]) for index in range(0,min(len(words)-2,12),3))
    topics=[]
    for value in values:
        cleaned=phrase(value)
        if not cleaned or not 2<=len(cleaned.split())<=4:continue
        if cleaned.casefold() in {topic.casefold() for topic in topics}:continue
        topics.append(cleaned)
    return topics[:6]


def fallback_media_terms(project, model):
    seeds=activity_phrases(project,model)
    if not seeds:raise ValueError('No searchable product activity.')
    return {'tiktok':[seeds[0]+' tips',(seeds[1] if len(seeds)>1 else seeds[0])+' app demo']}


def queries(project,model,lane,platform):
    if platform not in ('TikTok','Instagram','Reddit','X'):raise ValueError('Unsupported native platform.')
    if lane=='conversations':
        compiled=model.get('native_'+platform.lower()+'_query_plan')
        if isinstance(compiled,list) and compiled:
            from native_conversations import search_input
            for query in compiled:search_input(query,platform=platform)
            # Keep planned customer intent first. Rotate user topics through
            # subsequent scheduled searches without another model-planning call.
            hints=[s.name for s in getattr(project,'followed_sources',[]) if s.kind=='topic' and s.platform==platform]
            hints += list(getattr(project,'keywords',[]))
            extras=[]
            for hint in hints:
                cleaned=phrase(hint)
                if cleaned and len(cleaned.split())>=2:extras.append(cleaned)
            return list(dict.fromkeys([*compiled,*extras]))
    base=[phrase(q,instagram=platform=='Instagram') for q in model.get(lane,[])]
    # Alternate publisher-grounded niche searches and user-provided topics.
    # A keyword is an exploration hint, never a claimed product feature.
    extra=[]
    if lane=='for_you':
        extra=[phrase(source.name,instagram=platform=='Instagram') for source in getattr(project,'followed_sources',[]) if source.platform==platform and source.kind=='topic']
        extra += [phrase(k,instagram=platform=='Instagram') for k in getattr(project,'keywords',[])]
        extra += [phrase(k,instagram=platform=='Instagram') for k in model.get('adjacent_topics',[])]
    elif lane=='competitors':
        for competitor in (name.strip() for value in project.competitors for name in value.split(',') if name.strip()):
            if '://' in competitor:
                parsed=urlsplit(competitor)
                competitor=parsed.path.strip('/').lstrip('@') or (parsed.hostname or '').removeprefix('www.').split('.')[0]
            extra.append(phrase(competitor+' app',instagram=platform=='Instagram'))
    result=[]
    for index in range(max(len(base),len(extra))):
        for group in (base,extra):
            if index<len(group) and group[index] and group[index] not in result:result.append(group[index])
    return result


def collect(task):
    """No web-index fallback, including scheduled/background acquisition."""
    from research_providers import discover_native_media
    from native_conversations import discover
    platform=task['platform']; query=task['query']
    if platform in ('TikTok','Instagram'):
        rows=discover_native_media([query],20,90,platform,platform=='Instagram')
    else:rows=discover(query,20,90,platform)
    return [{**row,'retrieved_for':'discover' if task['lane']=='for_you' else task['lane']} for row in rows]
