"""GNSS118 internal candidate: explicit standard and historical contracts."""
import argparse,copy,json,re,sys,subprocess,tempfile,os
from pathlib import Path
from datetime import datetime,timezone
B=Path(__file__).resolve().parent
sys.path.insert(0,str(B/'src'))
import common as u
VERSION='GNSS118_INTERNAL_HANDOFF_CANDIDATE_V1'
CORE_VERSION='GNSS118_INTERNAL_TOOLBOX_CANDIDATE_V1'
STANDARD='INTERNAL_STANDARD_RUN_V1';HISTORICAL='EXACT_HISTORICAL_REGRESSION_V1'
CORE=B/'vendor/recorded_core'
REC=None
def get_recorder():
    global REC
    if REC is None:
        try: REC=u.module(CORE/'tools/experiments/dop_recorder.py','e18_dop_recorder')
        except ModuleNotFoundError as e:
            raise u.Rejected('NUMPY_MISSING' if e.name=='numpy' else 'DEPENDENCY_MISSING',str(e))
        except ImportError as e: raise u.Rejected('NUMPY_IMPORT_FAILED',str(e))
    return REC
ACTIVE_RUN=None

def package_identity():
    p=B/'version_manifest.json';m=u.load(p)
    u.need(m['version']==VERSION,'VERSION_MISMATCH')
    listed=set()
    for row in m['files']:
        f=(B/row['path']).resolve();u.need(f.is_relative_to(B) and f!=p,'MANIFEST_PATH_INVALID')
        u.need(row['path'] not in listed,'MANIFEST_DUPLICATE');listed.add(row['path']);u.bound(f,row['sha256'],'PACKAGE_FILE')
    actual={f.relative_to(B).as_posix() for f in B.rglob('*') if f.is_file() and f!=p}
    u.need(actual==listed,'PACKAGE_INVENTORY_MISMATCH')
    runner=u.module(CORE/'tools/experiments/run_frozen_analysis.py','e17_snapshot_check')
    identity=runner.read_snapshot(CORE,CORE/'SOURCE_MANIFEST.json')
    u.need(identity['baseline_id']==CORE_VERSION and identity['snapshot_id'].startswith('GNSS118-E17-CORE-'),'DERIVED_VERSION_MISMATCH')
    return u.ident(p)

def historical_contract(path,digest,c):
    path=Path(path).resolve();u.bound(path,digest,'HISTORICAL_CONTRACT');h=u.load(path)
    u.need(h['version']==HISTORICAL and h['science']==c['science'],'HISTORY_SCIENCE_MISMATCH')
    u.need(h['input_sha256']=={k:v['sha256'] for k,v in c['inputs'].items()},'HISTORY_INPUT_IDENTITY_MISMATCH')
    v=h['comparison'];u.need(v['enabled'] is True and v['policy']=='EXACT_REPLAY_SCIENCE_V1' and h['expected_fields']==12965,'HISTORY_POLICY_INVALID')
    u.need(set(v['files'])=={'results','terms','qualification','observations'},'HISTORY_FILES_INVALID')
    u.need(v['gps_ns']==[str(1305254533006000000+i*1000000000) for i in range(20)] and v['qualification_evidence_policy']=='SAME_REFERENCE_CONTRACT_V1','HISTORY_SCOPE_CHANGED')
    bindings=[u.ident(path)]
    for name in ['source_config','source_science_seal','source_manifest']:
        row=h[name];bindings.append(u.bound(Path(row['path']),row['sha256'],'HISTORY_SOURCE'))
    source=u.load(Path(h['source_config']['path']))
    u.need(source['science']==c['science'] and {k:v['sha256'] for k,v in source['inputs'].items()}==h['input_sha256'],'HISTORY_SOURCE_CONFIG_MISMATCH')
    sm=u.load(Path(h['source_manifest']['path']));cm=u.load(CORE/'SOURCE_MANIFEST.json')
    sd={r['path']:r['sha256'] for r in sm['files']};cd={r['path']:r['sha256'] for r in cm['files']}
    for name in ['configs/experiments/runtime/urbannav_spp_A.conf','configs/experiments/runtime/urbannav_spp_B.conf','configs/experiments/runtime/urbannav_final_residual_rules_v1.json','src/gnss_toolbox/evaluation/saved_qualification.py']:
        u.need(sd[name]==cd[name],'HISTORY_SCIENTIFIC_CODE_MISMATCH')
    seal=u.load(Path(h['source_science_seal']['path']));u.need(seal['runtime_complete'] is True,'HISTORY_SCIENCE_NOT_SEALED')
    parent=Path(h['source_science_seal']['path']).parent
    for name,sha in seal['files'].items():bindings.append(u.bound(parent/name,sha,'HISTORY_SEALED_OUTPUT'))
    for row in v['files'].values():
        f=Path(row['path']);u.need(f.is_absolute() and f.parent==parent and seal['files'].get(f.name)==row['sha256'],'HISTORY_SEAL_RELATION_INVALID');bindings.append(u.bound(f,row['sha256'],'HISTORY_OUTPUT'))
    return h,bindings

def preflight(config_path,probe=True):
    cp=u.resolve(Path.cwd(),str(config_path));u.need(cp.is_file(),'CONFIG_MISSING',cp);c=u.load(cp)
    required={'version','mode','run_id','python','inputs','science','output_root','dop_recording','numerical_certificate','historical_comparison'}
    u.need(set(c)==required,'CONFIG_SCHEMA_INVALID');u.need(c['version']==VERSION,'VERSION_MISMATCH')
    u.need(c['mode'] in [STANDARD,HISTORICAL],'MODE_INVALID')
    science=u.load(B/'science_contract.json')
    u.need(isinstance(c['science'],dict) and set(c['science'])==set(science),'SCIENTIFIC_CONFIG_MISSING')
    u.need(c['science']['methods']==science['methods'],'UNSUPPORTED_METHOD')
    u.need(c['science']['window']==science['window'],'INVALID_TIME_RANGE');u.need(c['science']==science,'SCIENTIFIC_CONFIG_MISMATCH')
    u.need(type(c['dop_recording']) is bool and type(c['numerical_certificate']) is bool,'RECORDING_MODE_INVALID')
    u.need(not c['numerical_certificate'] or c['dop_recording'],'CERTIFICATE_REQUIRES_RECORDING')
    if c['mode']==STANDARD:u.need(c['historical_comparison'] is None,'STANDARD_HISTORY_NOT_ALLOWED')
    else:u.need(isinstance(c['historical_comparison'],dict) and set(c['historical_comparison'])=={'path','sha256'},'HISTORICAL_CONTRACT_REQUIRED')
    rid=c['run_id'];u.need(isinstance(rid,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',rid) and not rid.endswith('.') and rid.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]},'RUN_ID_INVALID')
    out=u.resolve(cp.parent,c['output_root']);target=out/rid
    u.need(out!=cp.parent and out.is_relative_to(cp.parent) and not (out==B or out.is_relative_to(B) or B.is_relative_to(out)),'OUTPUT_PATH_PROTECTED')
    u.need(not any(x in {'.git','.codex','.agents','vendor','audit','src','controls','internal_candidate'} for x in out.relative_to(cp.parent).parts),'OUTPUT_PATH_PROTECTED')
    u.need(not target.exists(),'RUN_ID_EXISTS')
    u.need(set(c['inputs'])=={'obs','nav','dll'},'INPUT_SCHEMA_INVALID')
    dep=u.load(B/'external_inputs_contract.json');bindings=[u.ident(cp),package_identity()]
    for k,row in c['inputs'].items():
        u.need(set(row)=={'path','sha256'},'INPUT_SCHEMA_INVALID');f=u.resolve(cp.parent,row['path']);bindings.append(u.bound(f,row['sha256'],k.upper()))
        u.need(row['sha256']==dep['files'][k]['sha256'],'INPUT_PROFILE_MISMATCH')
        u.need(not out.is_relative_to(f.parent) and not f.is_relative_to(out),'OUTPUT_PATH_PROTECTED');row['path']=str(f)
    py=c['python'];u.need(set(py)=={'path','sha256','environment'},'PYTHON_SCHEMA_INVALID');f=u.resolve(cp.parent,py['path']);bindings.append(u.bound(f,py['sha256'],'PYTHON'))
    py['path']=str(f);u.need(f==Path(sys.executable).resolve(),'PUBLIC_INTERPRETER_MISMATCH')
    expected=u.load(B/'environment_contract.json')['tested_profile'];u.need(py['environment']==expected,'ENVIRONMENT_CONTRACT_MISMATCH')
    h=None
    if c['mode']==HISTORICAL:
        hp=u.resolve(cp.parent,c['historical_comparison']['path']);h,hb=historical_contract(hp,c['historical_comparison']['sha256'],c);bindings+=hb;c['historical_comparison']['path']=str(hp)
    if probe:
        env=u.environment_probe(f,Path(c['inputs']['dll']['path']));u.need(all(env.get(k)==v for k,v in expected.items()),'DEPENDENCY_CONTRACT_MISMATCH')
        out.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.e17-write-probe-',dir=out);os.close(fd);Path(tmp).unlink()
    else:env={'status':'TEST_PROBE_SKIPPED','navigation_calls':0}
    return {'status':'PREFLIGHT_READY','version':VERSION,'config':c,'config_path':str(cp),'target':str(target),'output_root':str(out),'environment':env,'bindings':bindings,'navigation_calls':0,'write_probe':probe}

def science_evidence(run):
    s={'status':'UNKNOWN','navigation_calls':'UNKNOWN','started_calls':'UNKNOWN','result_sealed':False}
    try:
        p=u.load(run/'replay/execution_progress.json');s.update(navigation_calls=p.get('top_level_returned','UNKNOWN'),started_calls=p.get('top_level_started','UNKNOWN'))
        s['status']=u.load(run/'run_metadata.json')['status'];seal=u.load(run/'replay/runtime_outputs_seal.json')
        s['result_sealed']=seal['runtime_complete'] is True and len(seal['files'])==8 and all(u.sha(run/'replay'/name)==digest for name,digest in seal['files'].items())
    except (OSError,KeyError,ValueError):pass
    return s

def qualification(run):
    results=u.load(run/'replay/fresh_results.json');quals=u.csvrows(run/'replay/epoch_qualification.csv')
    summary=u.qualification_summary(results,quals);rows=u.csvrows(run/'replay/native_gps_fields.csv')
    u.need(len(rows)==140 and sum(r['eligible']=='True' for r in rows)==117,'OBS_SUPPORT_MISMATCH')
    w=u.load(run/'replay/window_summary.json');u.need(w['requested_slots']==w['OBS_matched']==20 and w['top_level_calls']==40,'WINDOW_CALLS_MISMATCH')
    return {'status':'CHECKED','summary':summary,'reference_precision_certification':False,'candidate_code_rows':140,'eligible_code_rows':117}

def audit_records(run,c,save=True):
    if not c['dop_recording']:
        u.need(not (run/'replay/dop_evidence').exists(),'UNREQUESTED_RECORDING');return {'status':'NOT_REQUESTED','recorded_requests':0},{'status':'NOT_REQUESTED','certified_requests':0}
    records=get_recorder().verify(run/'replay/dop_evidence',40);index={tuple(r['key']):r for r in records};certs=[]
    if c['numerical_certificate']:
        from certify import certificate
    for result in u.load(run/'replay/fresh_results.json'):
        r=index[(result['gps_ns'],result['method'])]
        u.need(r['production_source_hash']==u.sha(CORE/'tools/experiments/replay_urbannav.py'),'PRODUCTION_SOURCE_MISMATCH')
        raw=u.load(run/f"replay/raw_return_{result['method']}_{result['epoch_index']}.json");good=[x for x,z in zip(raw['model_rows'],raw['used']) if z]
        u.need(r['used_satellite_order']==result['used_satellites']==[x['sv'] for x in good],'SATELLITE_RECORD_MISMATCH')
        u.need(r['original_az_el_strings']==[[x['az_rad'],x['el_rad']] for x in good],'ANGLE_RECORD_MISMATCH')
        u.need(all((None if result[k] is None else result[k].hex())==r['DOP_hex'][k] for k in r['DOP']),'DOP_RECORD_MISMATCH')
        if c['numerical_certificate']:
            u.need(r['dop_defined_or_undefined']=='DEFINED','NUMERICAL_CERTIFICATE_UNAVAILABLE')
            z=certificate(r['H']['values'],r['G']['values'],r['Q']['values'],r['DOP'],r['diagonal_sums']['values']);z.update(key=r['key'],record_sha256=u.sha(run/'replay/dop_evidence'/r['request_id']/'record.json'));certs.append(z)
    if c['numerical_certificate'] and save:u.write(run/'production_certificates.json',certs)
    cert={'status':'CERTIFIED','certified_requests':40,'valid_region':sum(x['GDOP_gate']=='VALID' for x in certs),'above_30':sum(x['GDOP_gate']=='INVALID_ABOVE_30' for x in certs),'scope':'finite numerical input only; no override of strict regression'} if c['numerical_certificate'] else {'status':'NOT_REQUESTED','certified_requests':0}
    return {'status':'COMPLETE','recorded_requests':40,'matrix_identity_verified':True},cert

def assemble(science,recording,q,history,cert,error=None):
    recok=recording.get('status')=='NOT_REQUESTED' or (recording.get('status')=='COMPLETE' and recording.get('matrix_identity_verified') is True and recording.get('recorded_requests')==40)
    ok=not error and science['status']=='SUCCEEDED' and science['navigation_calls']==40 and science['result_sealed'] and recok and q.get('status')=='CHECKED' and history['status'] in ['NOT_REQUESTED','PASS'] and cert['status'] in ['NOT_REQUESTED','CERTIFIED']
    state='SUCCEEDED' if ok else 'REGRESSION_FAILED' if history['status']=='FAIL' else 'RUNTIME_OR_EVIDENCE_BLOCKED'
    return {'version':VERSION,'science_execution':science,'runtime_recording':recording,'qualification':q,'historical_regression':history,'numerical_certificate':cert,'delivery':{'status':'COMPLETE' if ok else 'EVIDENCE_ONLY_NOT_ACCEPTED','fully_sealed':ok},'overall_status':state,'exit_code':0 if ok else 2,'error':error}

def comparison(run,contract,digest,c):
    h,_=historical_contract(contract,digest,c)
    engine=u.module(CORE/'tools/experiments/replay_urbannav.py','e17_compare_engine')
    comparator=u.module(CORE/'tools/experiments/window_urbannav.py','e17_compare_only')
    result=comparator.optional_comparison(h,run/'replay',Path(contract).parent,engine)
    u.need(sum(result['checked_fields'].values())==12965,'COMPARISON_DENOMINATOR_CHANGED')
    u.need(result['float_tolerance']==0,'COMPARISON_TOLERANCE_CHANGED')
    return result

def run(config):
    global ACTIVE_RUN
    p=preflight(config);c=p['config'];target=Path(p['target']);control=Path(p['output_root'])/'_control'/c['run_id'];control.mkdir(parents=True,exist_ok=False)
    u.write(control/'preflight.json',p);rt=control/'runtime.json'
    prep=u.module(CORE/'tools/experiments/prepare_baseline_config.py','e17_prepare')
    prep.prepare(CORE,{k:Path(v['path']) for k,v in c['inputs'].items()},Path(c['python']['path']),Path(p['output_root']),rt)
    rc=u.load(rt);u.need(rc['runtime']['window']==c['science']['window'] and rc['comparison']=={'enabled':False},'GENERATED_SCIENCE_CHANGED')
    rc['runtime']['dop_recording']=c['dop_recording'];rt.write_text(json.dumps(rc,indent=2),encoding='utf8')
    cmd=[c['python']['path'],'-I','-B','-X','utf8',str(CORE/'tools/experiments/run_frozen_analysis.py'),'--config',str(rt),'--run-id',c['run_id']]
    ACTIVE_RUN=target
    start=datetime.now(timezone.utc).isoformat();recording={'status':'UNKNOWN','recorded_requests':'UNKNOWN'};q={'status':'UNKNOWN'};cert={'status':'NOT_RUN','certified_requests':0};hist={'status':'NOT_REQUESTED' if c['mode']==STANDARD else 'NOT_RUN','contract':None if c['mode']==STANDARD else 'EXACT_REPLAY_SCIENCE_V1'};error=None
    try:
        cp=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',timeout=150)
        u.write(control/'science_command.json',{'command':cmd,'start_utc':start,'end_utc':datetime.now(timezone.utc).isoformat(),'exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr})
        science=science_evidence(target);u.need(cp.returncode==0 and science['result_sealed'],'SCIENCE_EXECUTION_FAILED',cp.stderr)
        q=qualification(target);u.write(target/'qualification_summary.json',q)
        recording,cert=audit_records(target,c)
        if c['mode']==HISTORICAL:
            h=c['historical_comparison'];cmp=comparison(target,h['path'],h['sha256'],c);u.write(target/'historical_comparison.json',cmp)
            hist={'status':'PASS' if cmp['all_equal'] else 'FAIL','contract':'EXACT_REPLAY_SCIENCE_V1','checked_fields':sum(cmp['checked_fields'].values()),'mismatched_fields':len(cmp['differences'])}
        for row in p['bindings']:u.bound(Path(row['path']),row['sha256'],'PROTECTED_INPUT')
    except Exception as e:error=repr(e)
    science=science_evidence(target)
    receipt=assemble(science,recording,q,hist,cert,error)
    if target.is_dir():
        u.write(target/'execution_contract.json',{'version':VERSION,'mode':c['mode'],'config':c,'package_manifest':package_identity(),'bindings':p['bindings']+[u.ident(rt)],'science_command':u.ident(control/'science_command.json') if (control/'science_command.json').is_file() else None})
        u.write(target/'public_receipt.json',receipt)
        files=[{'path':f.relative_to(target).as_posix(),'sha256':u.sha(f)} for f in sorted(target.rglob('*')) if f.is_file()]
        u.write(target/'delivery_seal.json',{'version':VERSION,'files':files,'fully_sealed':receipt['delivery']['fully_sealed']})
    return receipt

def verify(run):
    run=u.resolve(Path.cwd(),str(run));package_identity();seal=u.load(run/'delivery_seal.json');u.need(seal['version']==VERSION,'VERSION_MISMATCH')
    listed=set()
    for r in seal['files']:
        p=(run/r['path']).resolve();u.need(p.is_relative_to(run) and p!=run/'delivery_seal.json','SEAL_PATH_ESCAPE');u.bound(p,r['sha256'],'SEALED_OUTPUT');u.need(r['path'] not in listed,'DUPLICATE_SEAL_PATH');listed.add(r['path'])
    actual={f.relative_to(run).as_posix() for f in run.rglob('*') if f.is_file() and f!=run/'delivery_seal.json'};u.need(actual==listed,'SEALED_INVENTORY_CHANGED')
    c=u.load(run/'execution_contract.json');u.need(c['package_manifest']['sha256']==u.sha(B/'version_manifest.json'),'RUN_PACKAGE_CHANGED')
    for r in c['bindings']:u.bound(Path(r['path']),r['sha256'],'BOUND_SOURCE')
    receipt=u.load(run/'public_receipt.json');u.need(science_evidence(run)==receipt['science_execution'],'SCIENCE_RECEIPT_MISMATCH')
    if receipt['delivery']['fully_sealed']:
        u.need(qualification(run)==receipt['qualification'],'QUALIFICATION_RECEIPT_MISMATCH')
        if c['config']['dop_recording']:get_recorder().verify(run/'replay/dop_evidence',40)
    receipt['this_verify_navigation_calls']=0;receipt['read_only_verification']='PASS';return receipt

def compare(run,contract,digest):
    before=verify(run);u.need(before['science_execution']['result_sealed'],'UNSEALED_SCIENCE')
    run=Path(run).resolve();c=u.load(run/'execution_contract.json')['config'];result=comparison(run,contract,digest,c)
    return {'operation':'READ_ONLY_COMPARE','comparison_contract':'EXACT_REPLAY_SCIENCE_V1','historical_contract':u.ident(Path(contract)),'navigation_calls':0,'result':result,'exit_code':0 if result['all_equal'] else 2}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',action='version',version=VERSION);sub=parser.add_subparsers(dest='command',required=True)
    for n in ['preflight','run']:sub.add_parser(n).add_argument('--config',type=Path,required=True)
    sub.add_parser('verify').add_argument('--run-dir',type=Path,required=True)
    a=sub.add_parser('compare');a.add_argument('--run-dir',type=Path,required=True);a.add_argument('--contract',type=Path,required=True);a.add_argument('--contract-sha256',required=True)
    args=parser.parse_args()
    try:
        if args.command=='preflight':
            result=preflight(args.config);result={k:result[k] for k in ['status','version','target','environment','navigation_calls','write_probe']}
        elif args.command=='run':result=run(args.config)
        elif args.command=='verify':result=verify(args.run_dir)
        else:result=compare(args.run_dir,args.contract,args.contract_sha256)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return result.get('exit_code',0)
    except Exception as e:
        failure={'version':VERSION,'overall_status':'REJECTED','reason_code':getattr(e,'code',type(e).__name__),'detail':str(e),'navigation_calls':0,'exit_code':2}
        if ACTIVE_RUN is not None:
            failure['science_execution']=science_evidence(ACTIVE_RUN);failure['navigation_calls']=failure['science_execution']['navigation_calls']
        print(json.dumps(failure,ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
