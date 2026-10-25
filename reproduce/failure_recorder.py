"""Read-only evidence serializer. No GNSS invocation; UNKNOWN is never zero."""
import json,hashlib,argparse
from pathlib import Path
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def record(run,comparison=None):
    out={'science_execution':{'status':'UNKNOWN','navigation_calls':'UNKNOWN','result_sealed':'UNKNOWN'},'regression':{'status':'UNKNOWN','mismatched_fields':'UNKNOWN'},'delivery':{'fully_sealed':False,'status':'NOT_CERTIFIED'},'overall_status':'EVIDENCE_UNAVAILABLE','exit_code':2,'this_tool_navigation_calls':0,'evidence_errors':[]}
    try:
        meta=load(run/'run_metadata.json');summary=load(run/'replay/window_summary.json');progress=load(run/'replay/execution_progress.json')
        out['science_execution']['status']=meta.get('status','UNKNOWN')
        counts=[summary.get('top_level_calls'),progress.get('top_level_started'),progress.get('top_level_returned')]
        if all(type(n) is int and n>=0 for n in counts) and len(set(counts))==1:out['science_execution']['navigation_calls']=counts[0]
        else:out['evidence_errors'].append('CALL_ACCOUNTING_INCOMPLETE')
    except (OSError,ValueError,KeyError) as e:out['evidence_errors'].append('SCIENCE_RECEIPT_MISSING_OR_INVALID:'+type(e).__name__)
    try:
        seal=load(run/'replay/runtime_outputs_seal.json')
        checks=[]
        for n,h in seal['files'].items():
            p=(run/'replay'/n).resolve()
            if not p.is_relative_to((run/'replay').resolve()):raise ValueError('UNSAFE_SEAL_PATH')
            checks.append(hashlib.sha256(p.read_bytes()).hexdigest()==h)
        ok=bool(checks) and len(checks)==8 and all(checks) and seal.get('runtime_complete') is True
        out['science_execution']['result_sealed']=ok;out['science_execution']['sealed_file_count']=len(checks)
        if not ok:out['evidence_errors'].append('SCIENTIFIC_SEAL_MISMATCH')
    except (OSError,ValueError,KeyError) as e:out['evidence_errors'].append('SEAL_UNAVAILABLE:'+type(e).__name__)
    if comparison is not None:
        try:
            c=load(comparison);out['regression']={'status':'FAILED' if c['status']=='MISMATCH' else 'UNKNOWN','comparison_contract':c['policy'],'mismatched_fields':len(c['differences'])}
        except (OSError,ValueError,KeyError) as e:out['evidence_errors'].append('COMPARISON_UNAVAILABLE:'+type(e).__name__)
    else:out['regression']={'status':'NOT_REQUESTED','mismatched_fields':'UNKNOWN'}
    # No success seal is fabricated or inferred from an existing filename.
    out['delivery']['historical_delivery_file_exists']=(run/'e12_delivery.json').exists()
    if not out['evidence_errors']:
        if out['regression']['status']=='FAILED':out['overall_status']='REGRESSION_FAILED'
        elif comparison is None:out['overall_status']='READ_ONLY_EVIDENCE_RETURNED';out['exit_code']=0
    return out
def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--comparison',type=Path);a=p.parse_args();r=record(a.run_dir,a.comparison);print(json.dumps(r,indent=2));return r['exit_code']
if __name__=='__main__':raise SystemExit(main())
