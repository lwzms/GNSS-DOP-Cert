"""Non-navigation contract tests. Historical fixture is an explicit test argument."""
import argparse,copy,hashlib,importlib.util,json,shutil,subprocess,sys,tempfile
from pathlib import Path
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--history-contract',type=Path,required=True);ap.add_argument('--fixture-run',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('e17_toolbox_test',root/'toolbox.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
    base=t.u.load(args.config);area=args.output.resolve().parent/'cases';area.mkdir(exist_ok=False);results=[]
    def check(name,fn):
        try:detail=fn();results.append({'name':name,'status':'PASS','detail':detail})
        except Exception as e:results.append({'name':name,'status':'FAIL','detail':repr(e)})
    def expect(code,fn):
        try:fn()
        except Exception as e:
            assert code in str(e),(code,repr(e));return str(e)
        raise AssertionError('Expected rejection '+code)
    def config_case(name,edit):
        c=copy.deepcopy(base);c['run_id']='test_'+name;edit(c);p=area/(name+'.json');p.write_text(json.dumps(c),encoding='utf8');return p
    def pf(name,edit,code):return expect(code,lambda:t.preflight(config_case(name,edit),probe=False))
    check('package_identity',lambda:t.package_identity())
    check('public_CLI_version',lambda:subprocess.check_output([sys.executable,'-I','-B',str(root/'toolbox.py'),'--version'],text=True).strip())
    check('standard_preflight_without_history',lambda:t.preflight(config_case('standard',lambda c:None),probe=False)['status'])
    for key in ['obs','nav','dll']:
        check(key+'_missing',lambda key=key:pf(key+'_missing',lambda c:c['inputs'][key].update(path=str(area/(key+'.missing'))),key.upper()+'_MISSING'))
    check('obs_hash_wrong',lambda:pf('hash',lambda c:c['inputs']['obs'].update(sha256='0'*64),'OBS_HASH_MISMATCH'))
    check('unsupported_method',lambda:pf('method',lambda c:c['science'].update(methods=['HUBER']),'UNSUPPORTED_METHOD'))
    check('invalid_window',lambda:pf('window',lambda c:c['science']['window'].update(start_tow='1'),'INVALID_TIME_RANGE'))
    check('missing_science',lambda:pf('science',lambda c:c.update(science={}),'SCIENTIFIC_CONFIG_MISSING'))
    check('version_mismatch',lambda:pf('version',lambda c:c.update(version='RC1'),'VERSION_MISMATCH'))
    check('output_protected',lambda:pf('output',lambda c:c.update(output_root=str(root/'vendor')),'OUTPUT_PATH_PROTECTED'))
    check('standard_rejects_history',lambda:pf('unrequested',lambda c:c.update(historical_comparison={'path':'missing','sha256':'0'*64}),'STANDARD_HISTORY_NOT_ALLOWED'))
    check('history_requires_contract',lambda:pf('history_missing',lambda c:c.update(mode=t.HISTORICAL),'HISTORICAL_CONTRACT_REQUIRED'))
    def history_good():
        p=config_case('historical',lambda c:c.update(mode=t.HISTORICAL,historical_comparison={'path':str(args.history_contract.resolve()),'sha256':t.u.sha(args.history_contract)}))
        return t.preflight(p,probe=False)['status']
    check('explicit_historical_mode_bound',history_good)
    def duplicate():
        p=config_case('duplicate',lambda c:None);(area/'runs/test_duplicate').mkdir(parents=True);return expect('RUN_ID_EXISTS',lambda:t.preflight(p,probe=False))
    check('duplicate_run',duplicate)
    check('wrong_environment',lambda:pf('environment',lambda c:c['python']['environment'].update(numpy='0'),'ENVIRONMENT_CONTRACT_MISMATCH'))
    check('certificate_needs_recording',lambda:pf('cert',lambda c:c.update(dop_recording=False),'CERTIFICATE_REQUIRES_RECORDING'))
    check('recording_disabled_contract',lambda:t.preflight(config_case('disabled',lambda c:c.update(dop_recording=False,numerical_certificate=False)),probe=False)['status'])
    def complete_records():return {'requests':len(t.get_recorder().verify(args.fixture_run/'replay/dop_evidence',40))}
    check('complete_recorder_fixture',complete_records)
    def damaged():
        dst=area/'corrupt_records';shutil.copytree(args.fixture_run/'replay/dop_evidence',dst);f=next(dst.glob('*/Q.npy'));data=bytearray(f.read_bytes());data[-1]^=1;f.write_bytes(data)
        return expect('RECORDING_HASH_MISMATCH',lambda:t.get_recorder().verify(dst,40))
    check('damaged_recorder_rejected',damaged)
    def qualification():
        q=t.qualification(args.fixture_run);assert q['summary']['B']['accepted']==11 and q['summary']['B']['MODEL_VALID']['FALSE']==3
        assert q['summary']['A']['REFERENCE_VALID']['UNKNOWN']==20 and q['summary']['B']['REFERENCE_VALID']['UNKNOWN']==20
        return q
    check('accepted_model_reference_separated',qualification)
    def receipt_failure():
        r=t.assemble({'status':'SUCCEEDED','navigation_calls':40,'result_sealed':True},{'status':'COMPLETE','recorded_requests':40,'matrix_identity_verified':True},{'status':'CHECKED'},{'status':'FAIL'},{'status':'CERTIFIED'})
        assert r['exit_code']==2 and r['science_execution']['navigation_calls']==40;return r
    check('strict_failure_retains_calls',receipt_failure)
    def partial():
        r=t.assemble({'status':'FAILED','navigation_calls':13,'result_sealed':False},{'status':'UNKNOWN'},{'status':'UNKNOWN'},{'status':'NOT_REQUESTED'},{'status':'NOT_RUN'})
        assert r['exit_code']==2 and r['science_execution']['navigation_calls']==13;return r
    check('partial_calls_retained',partial)
    check('incomplete_verify',lambda:expect('No such file',lambda:t.verify(area/'missing_run')))
    def standard_receipt():
        r=t.assemble({'status':'SUCCEEDED','navigation_calls':40,'result_sealed':True},{'status':'NOT_REQUESTED'},{'status':'CHECKED'},{'status':'NOT_REQUESTED'},{'status':'NOT_REQUESTED'})
        assert r['exit_code']==0 and r['historical_regression']['status']=='NOT_REQUESTED';return r
    check('standard_NOT_REQUESTED_is_not_PASS',standard_receipt)
    def nohistory_opens():
        opened=[]
        def audit(event,a):
            if event=='open' and isinstance(a[0],str):opened.append(a[0])
        sys.addaudithook(audit)
        t.preflight(config_case('nohistory',lambda c:None),probe=False)
        bad=[p for p in opened if any(x in p.replace('\\','/') for x in ['e11_release','e12_thin_entry','e13_independent','e14_dop','e15_fixed','e16_production','engineering-e1'])]
        assert not bad,bad;return {'opened_count':len(opened),'forbidden_history_opens':bad}
    check('ordinary_preflight_no_history_access',nohistory_opens)
    # Explicit same-input frozen expressions; no navigation or DLL invocation.
    def diagnostics():
        rp=root/'vendor/recorded_core/tools/experiments/replay_urbannav.py';eng=t.u.module(rp,'e17_test_diagnostics')
        raw=t.u.load(next((args.fixture_run/'replay').glob('raw_return_A_*.json')));good=[x for x,z in zip(raw['model_rows'],raw['used']) if z]
        rows=t.u.load(args.fixture_run/'replay/fresh_results.json');initial=copy.deepcopy(rows[0]);off=copy.deepcopy(initial);on=copy.deepcopy(initial)
        eng.final_diagnostics(off,good)
        recorder=t.get_recorder().Recorder(area/'diagnostic_record',rp);eng.final_diagnostics(on,good,recorder);recorder.finish()
        assert off==on;assert len(t.get_recorder().verify(area/'diagnostic_record',1))==1
        return {'same_science':True,'offline_inputs':1}
    check('recorder_on_off_same_diagnostics',diagnostics)
    result={'tests':results,'passed':sum(r['status']=='PASS' for r in results),'failed':sum(r['status']=='FAIL' for r in results),'real_navigation_calls':0,'synthetic_navigation_calls':0,'historical_fixture':'read-only E16; not new validation data'}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'passed':result['passed'],'failed':result['failed']}));return bool(result['failed'])
if __name__=='__main__':raise SystemExit(main())
