"""Read-only, standard-library verification of the exported E16 paper evidence.

This does not run navigation, load a DLL, parse RINEX or certify physical accuracy.
"""
import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import math
import struct
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'evidence/urban_spp_fde_v1'
ARRAYS = ('angles', 'H', 'G', 'Q', 'Q_diagonal', 'diagonal_sums')
DOPS = ('gdop', 'pdop', 'hdop', 'vdop')

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def read_csv(p):
    with p.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

def key(row):
    return (str(row.get('gps_ns', row.get('gps_time_ns'))), row['method'])

def contained(root, relative):
    p = (root / relative).resolve()
    require(p.is_relative_to(root.resolve()) and not p.is_symlink(), 'UNSAFE_MANIFEST_PATH')
    return p

def check_manifest(base):
    manifest = load(base / 'manifest.json')
    expected = {v['path'] for v in manifest['files']}
    require(len(expected) == len(manifest['files']), 'DUPLICATE_MANIFEST_PATH')
    actual = {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
    require(actual == expected | {'manifest.json'}, 'EVIDENCE_INVENTORY_MISMATCH')
    for item in manifest['files']:
        p = contained(base, item['path'])
        require(digest(p) == item['sha256'] and p.stat().st_size == item['bytes'], 'EVIDENCE_HASH_MISMATCH:' + item['path'])
    for item in manifest['verification_code']:
        require(digest(contained(ROOT, item['path'])) == item['sha256'], 'VERIFIER_SOURCE_MISMATCH')
    return manifest

def read_npy(p, meta):
    raw = p.read_bytes()
    require(raw[:8] == b'\x93NUMPY\x01\x00', 'UNSUPPORTED_NPY_VERSION')
    length = struct.unpack('<H', raw[8:10])[0]
    header = ast.literal_eval(raw[10:10 + length].decode('latin1').strip())
    require(header['descr'] == '<f8' and header['fortran_order'] is False, 'NPY_DTYPE_OR_ORDER')
    require(list(header['shape']) == meta['shape'], 'NPY_SHAPE')
    payload = raw[10 + length:]
    require(len(payload) == 8 * math.prod(header['shape']), 'NPY_LENGTH')
    values = list(struct.unpack('<' + 'd' * (len(payload) // 8), payload))
    require(all(math.isfinite(x) for x in values), 'NONFINITE_ARRAY')
    require(hashlib.sha256(raw).hexdigest() == meta['sha256'], 'NPY_FILE_HASH')
    require(hashlib.sha256(payload).hexdigest() == meta['raw_C_sha256'], 'NPY_PAYLOAD_HASH')
    require([x.hex() for x in values] == meta['float_hex'], 'NPY_HEX_MISMATCH')
    nested = meta['values']
    flat = [x for row in nested for x in row] if len(header['shape']) == 2 else nested
    require([x.hex() for x in flat] == meta['float_hex'], 'JSON_ARRAY_MISMATCH')
    return nested

def verify(base=DEFAULT):
    base = Path(base).resolve()
    manifest = check_manifest(base)
    spec = importlib.util.spec_from_file_location('paper_exact_certificate', ROOT/'toolbox/src/certify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records, certs, stats = {}, {}, {}
    certified = arrays = 0
    for arm in 'AB':
        folder = base / 'arms' / arm
        results = load(folder/'fresh_results.json')
        quals = read_csv(folder/'qualifications.csv')
        saved_certs = load(folder/'production_certificates.json')
        require(len(results)==len(quals)==len(saved_certs)==40, 'REQUEST_ROW_COUNT')
        results = {key(v): v for v in results}
        quals = {key(v): v for v in quals}
        certs[arm] = {tuple(map(str, v['key'])): v for v in saved_certs}
        expected = {(str(1305254533006000000 + i * 1000000000), m) for i in range(20) for m in 'AB'}
        require(len(saved_certs) == 40 and set(results) == set(quals) == set(certs[arm]) == expected, 'REQUEST_COVERAGE')
        seal = load(folder/'original_recording_seal.json')
        original = {tuple(map(str, v['key'])): v for v in seal['records']}
        require(seal['complete'] and seal['recorded_requests'] == 40 and set(original) == expected, 'ORIGINAL_SEAL_COVERAGE')
        records[arm] = {}
        for record_path in sorted((folder/'matrices').glob('*/record.json')):
            r = load(record_path)
            k = key(r)
            require(k in expected and k not in records[arm], 'RECORD_KEY')
            require(tuple(map(str, r['key'])) == k, 'RECORD_KEY_BINDING')
            require(r['export_provenance']['original_record_sha256'] == original[k]['sha256'] == certs[arm][k]['source_record_sha256'], 'ORIGINAL_RECORD_BINDING')
            require(r['export_provenance']['runtime_environment'] == arm, 'ENVIRONMENT_BINDING')
            for name in ARRAYS:
                read_npy(contained(record_path.parent, r[name]['file']), r[name]); arrays += 1
            require(r['rank'] == 4 and r['dop_defined_or_undefined'] == 'DEFINED', 'UNEXPECTED_RANK_OR_DOP')
            require(len(r['used_satellite_order']) == r['H']['shape'][0], 'SATELLITE_ROW_MAPPING')
            for pair, values in zip(r['original_az_el_strings'], r['angles']['values']):
                require([float(s).hex() for s in pair] == [v.hex() for v in values], 'ANGLE_STRING_BINDING')
            for name in DOPS:
                require(r['DOP'][name].hex() == r['DOP_hex'][name] == results[k][name].hex(), 'RESULT_DOP_BINDING')
            c = module.certificate(r['H']['values'], r['G']['values'], r['Q']['values'], r['DOP'], r['diagonal_sums']['values'])
            require(all(c[name] == certs[arm][k][name] for name in c), 'RECOMPUTED_CERTIFICATE_MISMATCH')
            certified += 1
            records[arm][k] = r
        require(set(records[arm]) == expected, 'MISSING_MATRIX_RECORD')
        arm_stats = {}
        for method, label, accepted, model in [('A', 'SPP', 7, 18), ('B', 'SPP_FDE', 11, 17)]:
            rr = [v for k,v in results.items() if k[1] == method]
            qq = [v for k,v in quals.items() if k[1] == method]
            summary = {'requests':len(rr),'converged':sum(v['converged'] for v in rr),'accepted':sum(v['accepted'] for v in rr),'MODEL_TRUE':sum(v['MODEL_VALID']=='TRUE' for v in qq),'SOLVER_TRUE':sum(v['SOLVER_VALID']=='TRUE' for v in qq),'REFERENCE_UNKNOWN':sum(v['REFERENCE_VALID']=='UNKNOWN' for v in qq),'FINAL_STATE':dict(Counter(v['FINAL_STATE'] for v in qq))}
            require((summary['requests'],summary['converged'],summary['accepted'],summary['MODEL_TRUE'],summary['SOLVER_TRUE'],summary['REFERENCE_UNKNOWN']) == (20,20,accepted,model,accepted,20), 'QUALIFICATION_COUNT')
            require(sum(v['candidate_count'] for v in rr)==140 and sum(v['input_count'] for v in rr)==117, 'CODE_SUPPORT_COUNT')
            arm_stats[label] = summary
        fail_key = ('1305254541006000000', 'B')
        require(results[fail_key]['source_epoch_index'] == 548 and results[fail_key]['accepted'] is True and quals[fail_key]['MODEL_VALID']=='FALSE' and quals[fail_key]['FINAL_STATE']=='INVALID_MODEL_OUTPUT', 'ACCEPTED_MODEL_FALSE_LOST')
        gates = Counter(c['GDOP_gate'] for c in certs[arm].values())
        require(gates == {'VALID':36,'INVALID_ABOVE_30':4}, 'GDOP_REGION_COUNT')
        arm_stats['GDOP_regions'] = dict(gates)
        receipt = load(folder/'public_receipt.json')
        require(receipt['science_execution']['navigation_calls']==40 and receipt['runtime_recording']['recorded_requests']==40, 'HISTORICAL_CALL_COUNT')
        require(receipt['exit_code']==(0 if arm=='A' else 2), 'STRICT_FAILURE_LOST')
        stats[arm] = arm_stats
    pairs = read_csv(base/'dop_pairs.csv')
    require(len(pairs)==160, 'DOP_PAIR_COUNT')
    seen = set(); changes=Counter(); max_delta=Fraction(0); changed_requests=set()
    for row in pairs:
        k=(row['gps_ns'],row['method']); name=row['field']; identity=(k,name)
        require(identity not in seen and name in DOPS, 'DUPLICATE_OR_UNKNOWN_PAIR'); seen.add(identity)
        a,b=records['A'][k]['DOP'][name],records['B'][k]['DOP'][name]
        signed=Fraction(b)-Fraction(a)
        delta=abs(signed)
        require(float(row['A']).hex()==a.hex() and float(row['B']).hex()==b.hex() and Fraction(row['difference_exact'])==signed and float(row['difference'])==float(signed), 'CSV_DOP_MISMATCH')
        bound=sum((Fraction(certs[arm][k]['fields'][name]['total_absolute_bound']['fraction']) for arm in 'AB'),Fraction())
        require(delta<=bound and float(row['pair_bound'])==float(bound), 'PAIR_BOUND_MISMATCH')
        if a.hex()!=b.hex(): changes[name]+=1;changed_requests.add(k)
        max_delta=max(max_delta,delta)
    require(sum(changes.values())==131 and len(changed_requests)==38, 'DOP_DIFFERENCE_COUNT')
    stage={}
    for name in ['angles','H','G','Q']:
        n=diff=0
        for k in records['A']:
            aa,bb=records['A'][k][name]['float_hex'],records['B'][k][name]['float_hex']
            require(len(aa)==len(bb), 'MATRIX_SHAPE_PAIR')
            n+=len(aa);diff+=sum(a!=b for a,b in zip(aa,bb))
        stage[name]={'elements':n,'different':diff}
    require(stage=={'angles':{'elements':460,'different':0},'H':{'elements':920,'different':0},'G':{'elements':640,'different':256},'Q':{'elements':640,'different':594}},'PRODUCTION_STAGE_COUNTS')
    return {'status':'PASS','current_navigation_calls':0,'historical_navigation_calls':80,'files_checked':len(manifest['files']),'NPY_files_checked':arrays,'certificates_recomputed':certified,'DOP_pairs':160,'DOP_differences':dict(changes),'max_absolute_DOP_difference':float(max_delta),'max_absolute_DOP_difference_exact':str(max_delta),'production_matrix_comparison':stage,'qualification':stats,'scope':'Saved-output and finite-input arithmetic verification only; no new SPP/FDE, no raw-data qualification re-execution, no physical accuracy certification, no full 12965-field rerun.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,default=DEFAULT)
    args=parser.parse_args()
    try:
        print(json.dumps(verify(args.evidence_dir),indent=2,allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'FAIL','reason':str(exc),'current_navigation_calls':0}))
        return 2

if __name__=='__main__':
    sys.exit(main())
