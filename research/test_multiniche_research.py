"""Deterministic regression fixtures, not claims of live provider quality."""
from datetime import datetime,timezone
import pytest
from app import Project
from research_providers import evaluation_key
from research_quality import select_results,attention
from research_retrieval import model_key,save_model,cached_model
from live_discovery import search_plan
from demo_access import demo_results

CASES=[
 ('meal','Plan meals without wasting groceries.','Busy parents','I keep throwing away groceries. Does anyone know an app for weekly meal planning?','A quick meal-prep routine for busy parents','We built a meal planner that turns leftover groceries into dinners.'),
 ('study','Schedule revision to remember material before exams.','University students','I keep forgetting everything before exams. How do you plan revision?','My revision routine before exam week','We built a revision scheduler for students who forget material.'),
 ('invoice','Send overdue invoice reminders without awkward client follow-ups.','Freelance designers','My clients never pay invoices on time. Is there an app to send polite reminders?','When a freelancer has to chase another overdue invoice','We built an invoice reminder app for freelancers.'),
 ('accessibility','Read small text and inaccessible menus on a phone.','People with low vision','I cannot read restaurant menus with my low vision. Does anyone know a tool?','An accessible way to read a menu on your phone','We built a text magnifier for low vision users.'),
 ('pet','Keep track of medicine doses for dogs shared between family members.','Dog owners','I keep missing my dog medicine doses. Is there an app my family can share?','The morning routine with a dog on medication','We built a pet medication reminder app for families.'),
 ('nutrition','Track calories and understand daily nutritional intake.','Adults tracking their nutrition','I keep forgetting to log my meals. Does anyone know an easier calorie tracker?','How to estimate portions when eating out','We built a calorie tracker that logs meals from photos.'),
 ('travel','Organize travel bookings and plans in one itinerary.','Independent travellers','I keep losing my booking details. Is there an app for shared itineraries?','Packing and planning a weekend trip','We built a shared travel itinerary app.'),
 ('music','Plan instrument practice and track progress between lessons.','People learning an instrument','I keep forgetting what to practice. Does anyone know an app to organize lessons?','A useful warm-up routine for piano players','We built a music practice planner for students.'),
]

@pytest.mark.parametrize('name,problem,audience,question,creative,promo',CASES)
def test_three_lanes_and_preview_are_product_independent(name,problem,audience,question,creative,promo):
 p=Project(name=name,description=problem,problem=problem,audience=audience,platform='Web',status='unlaunched',category='other')
 def item(identifier,text,platform,intent):
  return {'id':identifier,'url':'https://example.com/'+identifier,'platform':platform,'kind':'Video' if platform=='TikTok' else 'Discussion','title':text,'summary':text,
          'author':'Fixture author','competitor':False,'tone':'neutral','published_at':datetime.now(timezone.utc).isoformat(),
          'metrics':{'provider':'fixture','checked_at':datetime.now(timezone.utc).isoformat(),'views':1800},
          'evaluation':{'provider':'gemini','checked_at':datetime.now(timezone.utc).isoformat(),'relevance':.7,'intent':intent,'evidence_quote':text,'reason':'Fixture evidence for '+problem,'need_status':'unresolved' if intent=='audience_problem' else 'unclear','request_quote':text if intent=='audience_problem' else ''}}
 chosen,report=select_results(p,[item(name+'-question',question,'Reddit','audience_problem'),item(name+'-creative',creative,'TikTok','creative_reference'),item(name+'-promo',promo,'Instagram','competitor')],require_evaluation=True)
 assert {s['intent'] for s in chosen}=={'conversations','discover','competitors'}
 assert next(s for s in chosen if s['intent']=='discover')['match_level']=='Adjacent'
 assert next(s for s in chosen if s['intent']=='conversations')['conversation_signal']['quote']==question
 assert next(s for s in chosen if s['intent']=='competitors')['competitor']
 public=demo_results({'discover':[s for s in chosen if s['section']=='discover'],'conversations':[s for s in chosen if s['section']=='conversations']})
 assert len(public['discover'])==2 and len(public['conversations'])==1
 assert report['measured_discovery']==1


def test_models_and_semantic_verdicts_do_not_leak_between_niches():
 projects=[Project(name=n,description=p,problem=p,audience=a,platform='Web',status='unlaunched',category='other') for n,p,a,*_ in CASES]
 assert len({model_key(p) for p in projects})==len(projects)
 source={'id':'same-post','title':'Original public post','summary':'Original public post body'}
 assert len({evaluation_key(p,source,'fixture-model') for p in projects})==len(projects)
 for p in projects:save_model(p,{'problem':p.problem})
 for p in projects:assert cached_model(p)=={'problem':p.problem}


def test_product_identity_is_part_of_competitor_verdict_cache():
 p=Project(name='One name',description=CASES[0][1],platform='Web',status='unlaunched',category='other')
 source={'id':'same-post','title':'Original public post','summary':'Full available original text'}
 assert evaluation_key(p,source,'model')!=evaluation_key(p.model_copy(update={'name':'New name'}),source,'model')


def test_relative_engagement_can_qualify_small_community_without_ten_thousand_views(monkeypatch):
 import research_retrieval
 monkeypatch.setattr(research_retrieval,'relative_attention',lambda source:{'status':'measured','ratio':3,'reason':'Three times the measured community median.'})
 source={'metrics':{'provider':'fixture','checked_at':datetime.now(timezone.utc).isoformat(),'views':180}}
 assert attention(source)['status']=='qualified'


def test_absent_baseline_does_not_claim_a_post_is_outperforming(monkeypatch):
 import research_retrieval
 monkeypatch.setattr(research_retrieval,'relative_attention',lambda source:{'status':'insufficient_baseline'})
 assert attention({'metrics':{'provider':'fixture','checked_at':datetime.now(timezone.utc).isoformat(),'views':500000}})['status']=='measured'
