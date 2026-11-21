"""Explicit acquisition policy: native platform search is the normal path.

Indexed search remains an opt-in diagnostic, never a silent native fallback.
No provider requests or spend reservations are made by this module.
"""
import os


def mode():
    value=os.environ.get('OUTLOUD_RETRIEVAL_MODE','native')
    if value not in ('native','indexed'):
        raise ValueError('Research retrieval mode must be native or indexed.')
    return value


def media_plan(terms,project=None):
    """Keep inspiration and competitor searches separate on both networks."""
    phrases=terms['tiktok']
    if len(phrases)!=2:raise ValueError('Separate inspiration and competitor phrases are required.')
    plan=[dict(platform=platform,lane=lane,phrases=[phrase])
          for lane,phrase in zip(('discover','competitors'),phrases)
          for platform in ('TikTok','Instagram')]
    if project is not None:
        from native_collection import phrase
        # One extra topic search per network, independent of exact feature fit.
        # Remaining topics rotate through the background collection schedule.
        seeds=[phrase(k,instagram=True) for k in getattr(project,'keywords',[])]
        seeds=[q for q in seeds if q]
        if seeds:
            for platform in ('TikTok','Instagram'):
                if not any(p['platform']==platform and p['phrases']==[seeds[0]] for p in plan):
                    plan.append(dict(platform=platform,lane='discover',phrases=[seeds[0]]))
    if project is not None:
        from native_collection import phrase, queries
        # Brand and use-case searches retrieve different originals from
        # anonymous category searches. Publication ownership is checked later.
        brief=terms.get('brief') or {}
        for platform in ('TikTok','Instagram'):
            for query in queries(project,brief,'competitors',platform)[:2]:
                task=dict(platform=platform,lane='competitors',phrases=[query])
                if task not in plan and (platform!='Instagram' or len(query.split())>=2):
                    plan.append(task)
        for source in [s for s in getattr(project, 'followed_sources', []) if s.kind=='topic' and s.platform in ('Instagram','TikTok')][:2]:
            if source.kind=='topic' and source.platform in ('Instagram','TikTok'):
                query=phrase(source.name,instagram=source.platform=='Instagram')
                task=dict(platform=source.platform,lane='discover',phrases=[query])
                if query and task not in plan:plan.append(task)
    return plan
