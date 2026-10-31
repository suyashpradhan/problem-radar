import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
class TestRadar(unittest.TestCase):
 def test_topics(self):self.assertIn('stripe-reconciliation',app.TOPICS)
 def test_pain(self):self.assertIsNotNone(app.PAIN.search('I manually reconcile CSVs every week'))
 def test_noise(self):self.assertIsNone(app.PAIN.search('hello world'))
 def test_clean_html(self):self.assertEqual(app.strip('<p>Manual &amp; tedious</p>'),'Manual & tedious')
 def test_score(self):
  row={'title':'manual reconciliation problem','body':'spreadsheet is tedious','score':4}
  self.assertGreater(app.evidence_score(row),0)
if __name__=='__main__':unittest.main()
