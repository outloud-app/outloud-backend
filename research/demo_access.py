"""Public demo projection: diversified visible matches and real, inert teaser excerpts."""
from copy import deepcopy

VISIBLE_PER_VIEW = 3


def preview_indices(sources):
    # Start with one result per available platform, preserving quality order.
    # Four platforms may have four visible results; never manufacture diversity.
    chosen=[]
    platforms=set()
    for index,source in enumerate(sources):
        if source['platform'] not in platforms:
            chosen.append(index)
            platforms.add(source['platform'])
        if len(chosen)==4:break
    limit=max(VISIBLE_PER_VIEW,len(chosen))
    chosen.extend(index for index in range(len(sources)) if index not in chosen and len(chosen)<limit)
    return set(chosen)


def demo_results(results):
    projected=deepcopy(results)
    projected.pop('quality_report',None)
    projected.pop('research_issues',None)
    projected.pop('refresh',None)
    lanes={"for_you":[],"competitors":[],"conversations":[]}
    for section in ('discover','conversations'):
        for source in projected.get(section,[]):
            lane='conversations' if section=='conversations' else 'competitors' if source.get('competitor') else 'for_you'
            lanes[lane].append(source)
    output={lane:[] for lane in lanes}
    locked_count=0
    for lane,sources in lanes.items():
        visible=preview_indices(sources)
        for index,source in enumerate(sources):
            if index in visible:
                output[lane].append(source)
        for index,source in enumerate(sources):
            if index in visible:continue
            locked_count+=1
            # These public snippets are intentionally supplied for a cosmetic teaser,
            # not an access-control boundary. No full text, source link, player or analysis.
            media=source.get('media') or {}
            image=media.get('url') if media.get('type')=='image' else media.get('poster')
            teaser={'title':source.get('title','')[:240], 'summary':source.get('summary','')[:420],
                    'author':source.get('author','')[:100], 'published_at':source.get('published_at')}
            if image and image.startswith('https://'):
                teaser['media']={'type':'image','url':image}
            output[lane].append({'id':source['id'],'locked':True,'section':'conversations' if lane=='conversations' else 'discover',
              'competitor':lane=='competitors','platform':source['platform'],'kind':source['kind'],
              'title':'Available in Outloud for Mac','summary':'','author':'','url':'','tone':'neutral','teaser':teaser})
    projected['discover']=output['for_you']+output['competitors']
    projected['conversations']=output['conversations']
    projected['preview']={'visible_per_view':VISIBLE_PER_VIEW,'max_visible_platforms':4,'locked_count':locked_count}
    return projected
