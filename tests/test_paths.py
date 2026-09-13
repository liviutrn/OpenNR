import sys,unittest,os,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from opennr_paths import external_path,require_external_output
class StorageTests(unittest.TestCase):
 def test_reject_d(self):
  with self.assertRaises(ValueError):require_external_output('D:/OpenNR-forbidden/new/cache')
 def test_junction(self):
  p=require_external_output(Path(__file__).resolve().parents[1]/'out'/'new-test-output')
  self.assertEqual(p.drive.lower(),'c:')
 def test_alias(self):
  if Path('X:/').exists():
   with self.assertRaises(ValueError):require_external_output('X:/new-test-output')
 def test_environment_and_explicit(self):
  with patch.dict(os.environ,{'OPENNR_OUTPUT_ROOT':'C:/OpenNR/Outputs/env-test'}):
   self.assertEqual(external_path('output'),Path('C:/OpenNR/Outputs/env-test'))
   self.assertEqual(external_path('output','E:/OpenNR_Builds/explicit-test'),Path('E:/OpenNR_Builds/explicit-test'))
 def test_unknown(self):
  with self.assertRaises(ValueError):external_path('unknown')
if __name__=='__main__':unittest.main()
