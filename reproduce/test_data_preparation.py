"""Small synthetic archive controls; no network, GNSS parsing or navigation."""
import gzip,hashlib,importlib.util,io,unittest,zipfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('download_case_data',Path(__file__).with_name('download_case_data.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class TestInputs(unittest.TestCase):
    def fixture(self,role):
        data=b'synthetic hash fixture only\n';name='fixture.obs'
        if role=='OBS':
            f=io.BytesIO()
            with zipfile.ZipFile(f,'w') as z:z.writestr(name,data)
            raw=f.getvalue()
        else:raw=gzip.compress(data)
        return raw,data,{'role':role,'archive_sha256':hashlib.sha256(raw).hexdigest(),'member':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    def test_zip(self):
        raw,data,s=self.fixture('OBS');self.assertEqual(m.extract_verified(raw,s),data)
    def test_gzip(self):
        raw,data,s=self.fixture('NAV');self.assertEqual(m.extract_verified(raw,s),data)
    def test_bad_archive(self):
        raw,data,s=self.fixture('OBS')
        with self.assertRaisesRegex(ValueError,'ARCHIVE_HASH'):m.extract_verified(raw+b'x',s)
    def test_bad_output_hash(self):
        raw,data,s=self.fixture('NAV');s['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'INPUT_HASH'):m.extract_verified(raw,s)
    def test_missing_member(self):
        raw,data,s=self.fixture('OBS');s['member']='other'
        with self.assertRaisesRegex(ValueError,'MEMBER_MISSING'):m.extract_verified(raw,s)
    def test_output_size(self):
        raw,data,s=self.fixture('NAV');s['bytes']=1
        with self.assertRaisesRegex(ValueError,'INPUT_HASH'):m.extract_verified(raw,s)
if __name__=='__main__':unittest.main(verbosity=2)
