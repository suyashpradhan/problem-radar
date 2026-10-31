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
