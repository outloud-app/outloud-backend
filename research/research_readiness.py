"""Read-only product acceptance report. No search, model calls, or link probes.
A source count cannot establish usefulness, availability, or customer retention.
"""
from datetime import datetime,timezone
from live_discovery import post_identity
from research_quality import select_results,QUALITY_VERSION,MAX_RESULTS,LANE_LIMITS,RELEASE_MINIMUM,MIN_CONVERSATIONS_PER_PLATFORM

TARGETS=dict(RELEASE_MINIMUM)


def timestamp(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None


def assess(project,workspace,now=None):
    now=datetime.now(timezone.utc).timestamp() if now is None else now
    candidates=workspace.get('discover',[])+workspace.get('conversations',[])
    # Reject catalog fixtures and invalid source URLs before counting anything.
    candidates=[s for s in candidates if isinstance(s,dict) and post_identity(s.get('url',''))]
    selected,quality=select_results(project,candidates,require_evaluation=True)
    lanes={}
    for lane,target in TARGETS.items():
        sources=[s for s in selected if s.get('intent')==lane]
        recent_metrics=0
        for source in sources:
            metrics=source.get('metrics') or {}
            checked=timestamp(metrics.get('checked_at'))
            if metrics.get('provider') and checked is not None and 0<=now-checked<=7*86400:
                recent_metrics+=1
        lanes[lane]={'target':target,'checked_matches':len(sources),'shortfall':max(0,target-len(sources)),
                     'platforms':sorted({s['platform'] for s in sources}),
                     'metrics_observed_within_seven_days':recent_metrics}
    platform_counts=quality['conversation_platform_counts']
    conversation_targets={platform:{'target':MIN_CONVERSATIONS_PER_PLATFORM,'checked_matches':count,
                                     'shortfall':max(0,MIN_CONVERSATIONS_PER_PLATFORM-count)}
                          for platform,count in platform_counts.items()}
    return {'name':project.name,'quality_policy':QUALITY_VERSION,'lanes':lanes,
            'target_volume_met':all(v['shortfall']==0 for v in (*lanes.values(),*conversation_targets.values())),
            'conversation_targets':conversation_targets,
            'selection_capacity':MAX_RESULTS,'target_total':sum(TARGETS.values()),
            'capacity_supports_target':all(LANE_LIMITS[lane]>=target for lane,target in TARGETS.items()),
            'source_availability':'Not verified by this offline report; working links need a separate live check.',
            'usefulness':'Semantic gates only; human acceptance still required.',
            'recurring_value':'Not established; requires observed customer use and time saved.',
            'existing_pipeline_blockers':quality['blockers'],
            'recorded_research_issues':workspace.get('research_issues',[])}
