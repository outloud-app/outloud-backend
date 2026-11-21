"""Re-run curation on already collected/evaluated originals. No provider calls."""
import sys,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'research'))
from app import Project
from research_providers import remembered_candidates,cached_evaluations
from research_quality import select_results,QUALITY_VERSION
from workspace_refresh import coverage
cases=[
 dict(name='Remote control sample',description='An iPhone app that controls smart televisions over local Wi-Fi. It replaces a lost physical TV remote with channel, volume and navigation controls.',audience='People who want to control their smart TV from a phone.',keywords=['TV remote','smart TV','lost remote']),
 dict(name='Reflection journal sample',description='A private journaling app for recording daily experiences, reflecting on feelings and finding recurring themes through guided writing prompts.',audience='People who want a regular personal reflection habit.',keywords=['journaling','reflection','writing prompt']),
 dict(name='Nutrition log sample',description='A food diary that helps people record meals and track daily calorie and nutrition intake. It simplifies food logging and reviewing eating habits.',audience='People keeping a daily food and nutrition diary.',keywords=['food diary','calorie','meal prep']),
]
import httpx
httpx.get=httpx.post=lambda *a,**k: (_ for _ in ()).throw(AssertionError('This review cannot use the network'))
report={'quality_version':QUALITY_VERSION,'provider_calls':0,'published':False,'products':[]}
for brief in cases:
 project=Project(**brief,platform='iOS',status='launched',category='other')
 candidates=remembered_candidates(project,cached_only=True)
 checked=cached_evaluations(project,candidates)
 selected,quality=select_results(project,checked,require_evaluation=True)
 report['products'].append({'name':project.name,'already_evaluated':len(checked),'lane_counts':quality['lane_counts'],
                            'quality_report':quality,'coverage':coverage(candidates,checked,selected),'results':selected})
 print(json.dumps({'name':project.name,'checked_results':len(selected),'lane_counts':quality['lane_counts'],'provider_calls':0}),flush=True)
(ROOT/'artifacts/cached-feed-review-2026-11-20.json').write_text(json.dumps(report,indent=2))
