import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error
import app


class DatabaseTest(unittest.TestCase):
 def setUp(self):
  self.tmp = tempfile.TemporaryDirectory()
  self.db = patch.object(app, 'DB', Path(self.tmp.name) / 'test.db')
  self.db.start()
  app.init()
  self.intervals = patch.object(app, 'SOURCE_INTERVALS', {'hn': 0, 'github': 0})
  self.intervals.start()

 def tearDown(self):
  self.intervals.stop()
  self.db.stop()
  self.tmp.cleanup()

 def item(self, topic):
  return dict(id='hn:123', topic=topic, source='Hacker News', title='manual work',
              body='tedious', url='https://news.ycombinator.com/item?id=123',
              published='2026-01-01T00:00:00Z', author='alice', score=0)

 def test_deduplication_preserves_multiple_topics(self):
  topics=list(app.TOPICS)[:2]
  with patch.object(app, 'find_hn', side_effect=lambda t,q:[self.item(t)]):
   first=app.scan(topics,'hn',2)
   second=app.scan(topics,'hn',2)
  self.assertEqual(first['added'],2)
  self.assertEqual(second['added'],0)
  self.assertEqual(len(app.evidence(topics[1])),1)

 def test_all_failed_is_failed_and_empty_success_is_complete(self):
  with patch.object(app,'find_hn',side_effect=TimeoutError('timeout')):
   self.assertEqual(app.scan([next(iter(app.TOPICS))],'hn',1)['status'],'failed')
  with patch.object(app,'find_hn',return_value=[]):
   self.assertEqual(app.scan([next(iter(app.TOPICS))],'hn',1)['status'],'complete')

 def test_partial_failure_and_persisted_requests(self):
  with patch.object(app,'find_hn',return_value=[]), patch.object(app,'find_github',side_effect=TimeoutError()):
   result=app.scan([next(iter(app.TOPICS))],queries_per_topic=1)
  self.assertEqual(result['status'],'partial')
  self.assertEqual(len(app.overview()['runs'][0]['requests']),2)

 def test_rate_limit_skips_remaining_queries(self):
  error=urllib.error.HTTPError('https://api.github.com',429,'rate limited',{'Retry-After':'120'},None)
  with patch.object(app,'find_github',side_effect=error) as fetch:
   result=app.scan([next(iter(app.TOPICS))],'github',3)
  self.assertEqual(fetch.call_count,1)
  self.assertEqual(result['status'],'failed')
  self.assertEqual(app.overview()['runs'][0]['requests'][1]['status'],'skipped')

 def test_active_run_blocks_overlap(self):
  with app.conn() as c:c.execute("INSERT INTO runs(started_at,status) VALUES(?,'running')",(app.now(),))
  with self.assertRaises(app.ScanBusy):app.scan()

 def test_invalid_item_rolls_back_batch_and_counts(self):
  topic=next(iter(app.TOPICS))
  bad=self.item(topic);bad['id']='hn:124';bad['published']=None
  with patch.object(app,'find_hn',return_value=[self.item(topic),bad]):
   result=app.scan([topic],'hn',1)
  self.assertEqual(result['added'],0)
  self.assertEqual(app.evidence(topic),[])

 def test_invalid_provider_response_is_not_empty_success(self):
  with patch.object(app,'request_json',return_value={'message':'bad'}):
   with self.assertRaises(ValueError):list(app.find_hn('x','q'))
   with self.assertRaises(ValueError):list(app.find_github('x','q'))

 def test_legacy_schema_migration(self):
  with app.conn() as c:
   c.execute('DROP TABLE evidence')
   c.execute('CREATE TABLE evidence(id TEXT PRIMARY KEY,topic TEXT NOT NULL,source TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,url TEXT NOT NULL,published TEXT,author TEXT,score INTEGER DEFAULT 0,found_at TEXT NOT NULL,UNIQUE(url,topic))')
   x=self.item(next(iter(app.TOPICS)))
   c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(x.values())+(app.now(),))
  app.init();app.init()
  with app.conn() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM evidence').fetchone()[0],1)
   self.assertEqual([r['name'] for r in c.execute('PRAGMA table_info(evidence)') if r['pk']],['id','topic'])

 def market_row(self, **changes):
  row=dict(pricing_status='verified',pricing='$20/month',verified_on=app.now()[:10],
           url='https://vendor.example',pricing_url='https://vendor.example/pricing',
           complaint='Missing feature',complaint_url='https://forum.example/post/1',
           complaint_published='2026-01-01',complaint_kind='independent_complaint')
  row.update(changes)
  return row

 def test_pricing_requires_explicit_current_vendor_verification(self):
  self.assertTrue(app.pricing_verified(self.market_row()))
  for change in [dict(pricing_status='unverified'),dict(verified_on='2020-01-01'),
                 dict(verified_on='2999-01-01'),dict(pricing_url='https://review.example'),
                 dict(pricing=''),dict(verified_on='bad')]:
   self.assertFalse(app.pricing_verified(self.market_row(**change)))

 def test_complaints_require_manual_classification_date_and_external_source(self):
  self.assertTrue(app.complaint_verified(self.market_row()))
  for change in [dict(complaint_kind='vendor_marketing'),dict(complaint_published=''),
                 dict(complaint_url='https://vendor.example/testimonial'),dict(complaint='')]:
   self.assertFalse(app.complaint_verified(self.market_row(**change)))

 def post(self, path, data):
  import io, json
  handler=object.__new__(app.Handler)
  body=json.dumps(data).encode()
  handler.headers={'Content-Length':str(len(body))}
  handler.rfile=io.BytesIO(body)
  handler.path=path
  with patch.object(handler,'send') as send:handler.do_POST()
  return send.call_args.args

 def test_api_rejects_non_object_and_invalid_fields(self):
  for data in [[],None,{'topic':[]},{'topic':123}]:
   self.assertEqual(self.post('/api/scan',data)[1],400)

 def test_research_workflow_and_edit(self):
  topic=next(iter(app.TOPICS))
  payload=dict(self.market_row(),topic=topic,name='Vendor',kind='paid')
  self.assertEqual(self.post('/api/competitors',payload)[0],{'ok':True})
  row=app.competitors(topic)[0]
  self.assertTrue(row['pricing_current'])
  payload.update(id=str(row['id']),pricing_status='unverified')
  self.post('/api/competitors',payload)
  self.assertEqual(len(app.competitors(topic)),1)
  self.assertFalse(app.competitors(topic)[0]['pricing_current'])
  self.post('/api/decision',dict(topic=topic,status='Needs research',target_buyer='Bookkeeper',underserved_gap='Unknown',next_step='Interview',notes='No go yet'))
  self.assertEqual(app.overview()['topics'][0]['target_buyer'],'Bookkeeper')

 def test_keyword_matches_and_duplicate_vendors_do_not_pass_gate(self):
  topic=next(iter(app.TOPICS))
  for _ in range(3):self.post('/api/competitors',dict(self.market_row(),topic=topic,name='Vendor',kind='paid'))
  group=app.overview()['topics'][0]
  self.assertEqual(group['paid_priced'],1)
  self.assertEqual(group['competitor_complaints'],1)
  self.assertEqual(group['gate'],'Needs more independent complaints')

 def test_seed_does_not_claim_verification(self):
  app.seed()
  self.assertEqual(app.competitors(next(iter(app.TOPICS))),[])
