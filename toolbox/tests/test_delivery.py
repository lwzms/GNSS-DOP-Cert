"""E18 non-navigation delivery tests. Every fixture is an explicit test input."""
import argparse,copy,hashlib,importlib.util,json,os,shutil,subprocess,sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--fixture-run',type=Path);args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.output_dir.resolve();assert not out.is_relative_to(root);out.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('e18_test',root/'toolbox.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
    base=t.u.load(args.config);rows=[];commands=[]
    def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name,fn):
        try:d=fn();rows.append(dict(name=name,status='PASS',detail=d))
        except Exception as e:rows.append(dict(name=name,status='FAIL',detail=repr(e)))
    def expect(code,fn):
        try:fn()
        except Exception as e:
            assert code in str(e),(code,repr(e));return str(e)
        raise AssertionError('Expected '+code)
    def case(name,edit):
        c=copy.deepcopy(base);c['run_id']='test_'+name;c['output_root']='results';edit(c);p=out/(name+'.json');save(p,c);return p
    def pf(name,edit,code):return expect(code,lambda:t.preflight(case(name,edit),probe=False))
    def cli(args,code=0,python=None):
        cmd=[python or sys.executable,'-I','-B','-X','utf8',str(root/'toolbox.py'),*args]
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',timeout=40);commands.append(dict(command=cmd,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr));assert p.returncode==code,(p.stdout,p.stderr);return p.stdout
    check('manifest_exact',lambda:t.package_identity())
    check('CLI_version',lambda:cli(['--version']).strip())
    check('CLI_help',lambda:cli(['--help'])[:120])
    check('ordinary_without_history',lambda:t.preflight(case('normal',lambda c:None),probe=False)['status'])
    for key in ['obs','nav','dll']:
        check(key+'_missing_actual_absolute_path',lambda key=key:pf('missing_'+key,lambda c:c['inputs'][key].update(path=str(out/(key+'.missing'))),key.upper()+'_MISSING'))
    check('wrong_OBS_hash',lambda:pf('hash',lambda c:c['inputs']['obs'].update(sha256='0'*64),'OBS_HASH_MISMATCH'))
    check('wrong_DLL_identity',lambda:pf('dllhash',lambda c:c['inputs']['dll'].update(sha256='0'*64),'DLL_HASH_MISMATCH'))
    check('missing_Python_preflight',lambda:pf('py',lambda c:c['python'].update(path=str(out/'python_missing.exe')),'PYTHON_MISSING'))
    check('method_rejected',lambda:pf('method',lambda c:c['science'].update(methods=['HUBER']),'UNSUPPORTED_METHOD'))
    check('window_rejected',lambda:pf('window',lambda c:c['science']['window'].update(start_tow='0'),'INVALID_TIME_RANGE'))
    check('scientific_config_missing',lambda:pf('scientific',lambda c:c.update(science={}),'SCIENTIFIC_CONFIG_MISSING'))
    check('wrong_version',lambda:pf('version',lambda c:c.update(version='RC1'),'VERSION_MISMATCH'))
    check('output_escape_rejected',lambda:pf('escape',lambda c:c.update(output_root='../escape'),'OUTPUT_PATH_PROTECTED'))
    check('candidate_output_rejected',lambda:pf('protected',lambda c:c.update(output_root=str(root/'outputs')),'OUTPUT_PATH_PROTECTED'))
    check('historical_contract_required',lambda:pf('history',lambda c:c.update(mode=t.HISTORICAL),'HISTORICAL_CONTRACT_REQUIRED'))
    check('ordinary_no_implicit_history',lambda:pf('implicit',lambda c:c.update(historical_comparison={'path':'missing','sha256':'0'*64}),'STANDARD_HISTORY_NOT_ALLOWED'))
    check('historical_missing_file',lambda:pf('missing_history',lambda c:c.update(mode=t.HISTORICAL,historical_comparison={'path':'absent_history.json','sha256':'0'*64}),'HISTORICAL_CONTRACT_MISSING'))
    def dup():
        p=case('dup',lambda c:None);(out/'results/test_dup').mkdir(parents=True);return expect('RUN_ID_EXISTS',lambda:t.preflight(p,probe=False))
    check('duplicate_run_id',dup)
    def paths():
        absolute=str(out/'missing.obs');assert t.u.resolve(out,absolute)==Path(absolute)
        assert t.u.resolve(out,'data/file.obs')==out/'data/file.obs'
        assert t.u.resolve(out,'../file.obs')==out.parent/'file.obs'
        # E17 fixture supplied a project-relative string as config-relative input.
        old=Path('E:/GNSS-Geo/.local/engineering/e17_internal_toolbox_20261025/audit/cases')
        wrong='.local/engineering/e17_internal_toolbox_20261025/audit/cases/obs.missing'
        duplicated=(old/Path(wrong)).resolve();assert duplicated==t.u.resolve(old,wrong)
        return {'absolute_preserved':absolute,'relative_base':str(out),'old_fixture_attempt':str(duplicated),'cause':'relative fixture argument under wrong declared base; not joining two absolute paths'}
    check('absolute_relative_and_E17_fixture_reproduction',paths)
    for name,value,code in [('drive_relative','C:abc','DRIVE_RELATIVE'),('root_relative','\\abc','ROOT_RELATIVE'),('UNC','\\\\server\\share\\file','UNC_OR_DEVICE'),('device','\\\\?\\C:\\file','UNC_OR_DEVICE'),('reserved','data/CON.txt','WINDOWS_RESERVED'),('trailing_dot','data/test.','WINDOWS_RESERVED'),('ADS','data/file:stream','PATH_COMPONENT'),('two_drives','C:/base/E:/data','PATH_COMPONENT')]:
        check('path_'+name,lambda value=value,code=code:expect(code,lambda:t.u.resolve(out,value)))
    # Public -S process actually lacks site-packages; no modification of any environment.
    def no_numpy():
        cmd=[sys.executable,'-I','-S','-B',str(root/'toolbox.py'),'--version'];p=subprocess.run(cmd,capture_output=True,text=True);assert p.returncode==0
        code="import sys,importlib.util,json;from pathlib import Path;s=importlib.util.spec_from_file_location('t',sys.argv[1]);t=importlib.util.module_from_spec(s);s.loader.exec_module(t)\ntry:t.get_recorder()\nexcept Exception as e:print(json.dumps({'code':getattr(e,'code',None),'detail':str(e)}))"
        p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(root/'toolbox.py')],capture_output=True,text=True);v=json.loads(p.stdout);assert v['code']=='NUMPY_MISSING';return v
    check('missing_NumPy_structured_and_version_available',no_numpy)
    def probe_missing_numpy():
        real=t.u.subprocess.run
        def no_site(cmd,**kw):return real([cmd[0],'-S',*cmd[1:]],**kw)
        t.u.subprocess.run=no_site
        try:return expect('NUMPY_MISSING',lambda:t.u.environment_probe(Path(sys.executable),Path(base['inputs']['dll']['path'])))
        finally:t.u.subprocess.run=real
    check('preflight_dependency_probe_missing_NumPy',probe_missing_numpy)
    def wrong_package(kind):
        dst=out/('package_'+kind);shutil.copytree(root,dst)
        f=dst/('unexpected.txt' if kind=='extra' else 'README.md')
        f.write_text('test mutation',encoding='utf8')
        code="import sys,importlib.util;s=importlib.util.spec_from_file_location('t',sys.argv[1]);t=importlib.util.module_from_spec(s);s.loader.exec_module(t)\ntry:t.package_identity()\nexcept Exception as e:print(str(e));sys.exit(2)"
        p=subprocess.run([sys.executable,'-I','-B','-c',code,str(dst/'toolbox.py')],capture_output=True,text=True)
        expected='PACKAGE_INVENTORY_MISMATCH' if kind=='extra' else 'PACKAGE_FILE_HASH_MISMATCH';assert p.returncode==2 and expected in p.stdout;return p.stdout
    check('source_change_rejected',lambda:wrong_package('changed'))
    check('unknown_extra_file_rejected',lambda:wrong_package('extra'))
    def receipts():
        q={'status':'CHECKED'};rec={'status':'COMPLETE','recorded_requests':40,'matrix_identity_verified':True};cert={'status':'CERTIFIED'}
        vals=[]
        for calls,history,complete in [(40,'NOT_REQUESTED',True),(40,'FAIL',True),(13,'NOT_REQUESTED',False),('UNKNOWN','NOT_REQUESTED',False)]:
            v=t.assemble({'status':'SUCCEEDED' if complete else 'FAILED','navigation_calls':calls,'result_sealed':complete},rec,q,{'status':history},cert)
            assert v['science_execution']['navigation_calls']==calls
            assert v['exit_code']==(0 if history=='NOT_REQUESTED' and complete else 2);vals.append(v)
        return {'synthetic_layered_receipts':vals,'executed_solver_calls':0}
    check('success_failure_partial_unknown_calls',receipts)
    def licensing():
        rows=t.u.load(root/'docs/license_ledger.json');assert any(x['redistribution_status'].startswith('UNKNOWN') for x in rows)
        forbidden={'.dll','.exe','.obs','.rnx','.ubx','.nmea','.whl'};bad=[str(p) for p in root.rglob('*') if p.is_file() and p.suffix.lower() in forbidden];assert not bad;return {'external_binary_data_files':bad,'public_licence_not_inferred':True}
    check('unknown_external_material_excluded',licensing)
    if args.fixture_run:
        original=args.fixture_run.resolve();assert not original.is_relative_to(root)
        check('saved_DOP_complete',lambda:{'historical_records':len(t.get_recorder().verify(original/'replay/dop_evidence',40)),'new_records':0})
        check('saved_qualification_not_upgraded',lambda:t.qualification(original))
        def particular():
            qs=t.u.csvrows(original/'replay/epoch_qualification.csv');rs=t.u.load(original/'replay/fresh_results.json');r=next(r for r in rs if r['method']=='B' and r['source_epoch_index']==548);q=next(q for q in qs if q['method']=='B' and q['gps_ns']==r['gps_ns']);assert r['accepted'] is True and q['MODEL_VALID']=='FALSE' and q['FINAL_STATE']=='INVALID_MODEL_OUTPUT';assert all(q['REFERENCE_VALID']=='UNKNOWN' for q in qs);return {'548':q,'reference_unknown':40}
        check('accepted_MODEL_FALSE_and_REFERENCE_UNKNOWN',particular)
        # This is a labelled validation fixture, not an E18 scientific execution.
        fixture=out/'TEST_FIXTURE_NOT_A_NEW_RUN';shutil.copytree(original,fixture)
        ec=t.u.load(fixture/'execution_contract.json');ec['version']=t.VERSION;ec['package_manifest']=t.package_identity();ec['bindings']=[];ec['test_fixture_only']=True;save(fixture/'execution_contract.json',ec)
        receipt=t.u.load(fixture/'public_receipt.json');receipt['version']=t.VERSION;save(fixture/'public_receipt.json',receipt)
        save(fixture/'delivery_seal.json',{'version':t.VERSION,'fully_sealed':True,'files':[{'path':p.relative_to(fixture).as_posix(),'sha256':t.u.sha(p)} for p in sorted(fixture.rglob('*')) if p.is_file() and p.name!='delivery_seal.json']})
        def verify():
            before={str(p):t.u.sha(p) for p in fixture.rglob('*') if p.is_file()};v=json.loads(cli(['verify','--run-dir',str(fixture)]));after={str(p):t.u.sha(p) for p in fixture.rglob('*') if p.is_file()};assert before==after and v['this_verify_navigation_calls']==0;return {'files_unchanged':len(before),'this_navigation_calls':0,'fixture_inherited_calls':40,'scope':'synthetic handoff metadata around unchanged E17 science'}
        check('complete_verify_read_only_fixture',verify)
        f=next((fixture/'replay/dop_evidence').glob('*/Q.npy'));d=bytearray(f.read_bytes());d[-1]^=1;f.write_bytes(d)
        check('corrupt_record_rejected',lambda:expect('RECORDING_HASH_MISMATCH',lambda:t.get_recorder().verify(fixture/'replay/dop_evidence',40)))
        check('corrupt_delivery_rejected',lambda:expect('SEALED_OUTPUT_HASH_MISMATCH',lambda:t.verify(fixture)))
    else:rows.append(dict(name='historical_fixture_checks',status='NOT_RUN',detail='explicit fixture not provided; ordinary use has no history dependency'))
    check('incomplete_verify_rejected',lambda:expect('No such file',lambda:t.verify(out/'absent_run')))
    result=dict(tests=rows,passed=sum(x['status']=='PASS' for x in rows),failed=sum(x['status']=='FAIL' for x in rows),not_run=sum(x['status']=='NOT_RUN' for x in rows),navigation_calls=0,DOP_recalculations=0,commands=commands)
    save(out/'test_results.json',result);print(json.dumps({k:result[k] for k in ['passed','failed','not_run','navigation_calls']}));return bool(result['failed'])
if __name__=='__main__':raise SystemExit(main())
