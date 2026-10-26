"""Portable negative controls; all mutations are limited to temporary copies."""
import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('evidence_verifier',HERE/'verify_paper_evidence.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)/'evidence'
        shutil.copytree(v.DEFAULT,self.base)
    def tearDown(self):
        self.temp.cleanup()
    def update_hash(self, relative):
        p=self.base/relative
        m=v.load(self.base/'manifest.json')
        for item in m['files']:
            if item['path']==relative:
                item.update(sha256=v.digest(p),bytes=p.stat().st_size)
        (self.base/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
    def test_extra_file_rejected(self):
        (self.base/'unexpected.txt').write_text('extra')
        with self.assertRaisesRegex(ValueError,'INVENTORY'):v.check_manifest(self.base)
    def test_missing_file_rejected(self):
        (self.base/'dop_pairs.csv').unlink()
        with self.assertRaisesRegex(ValueError,'INVENTORY'):v.check_manifest(self.base)
    def test_changed_file_rejected(self):
        with (self.base/'dop_pairs.csv').open('a') as f:f.write('changed')
        with self.assertRaisesRegex(ValueError,'HASH'):v.check_manifest(self.base)
    def test_wrong_verifier_identity_rejected(self):
        p=self.base/'manifest.json';m=v.load(p);m['verification_code'][0]['sha256']='0'*64
        p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'VERIFIER'):v.check_manifest(self.base)
    def test_matrix_payload_changed_rejected(self):
        p=next((self.base/'arms/A/matrices').glob('*/H.npy'))
        r=v.load(p.parent/'record.json');b=bytearray(p.read_bytes());b[-1]^=1;p.write_bytes(b)
        with self.assertRaises(ValueError):v.read_npy(p,r['H'])
    def test_matrix_json_changed_rejected(self):
        p=next((self.base/'arms/A/matrices').glob('*/H.npy'));r=v.load(p.parent/'record.json')
        r['H']['values'][0][0]+=1
        with self.assertRaisesRegex(ValueError,'JSON_ARRAY'):v.read_npy(p,r['H'])
    def test_missing_request_rejected_even_with_new_manifest(self):
        rel='arms/A/fresh_results.json';p=self.base/rel;d=v.load(p);d.pop();p.write_text(json.dumps(d));self.update_hash(rel)
        with self.assertRaisesRegex(ValueError,'REQUEST_ROW_COUNT'):v.verify(self.base)
    def test_certificate_forgery_rejected_even_with_new_manifest(self):
        rel='arms/A/production_certificates.json';p=self.base/rel;d=v.load(p);d[0]['rho']['fraction']='0';p.write_text(json.dumps(d));self.update_hash(rel)
        with self.assertRaisesRegex(ValueError,'CERTIFICATE_MISMATCH'):v.verify(self.base)
    def test_external_manifest_path_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNSAFE'):v.contained(self.base,'../outside')
    def test_readonly_manifest_check(self):
        before={p.relative_to(self.base).as_posix():v.digest(p) for p in self.base.rglob('*') if p.is_file()}
        v.check_manifest(self.base)
        after={p.relative_to(self.base).as_posix():v.digest(p) for p in self.base.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

if __name__=='__main__':unittest.main(verbosity=2)
