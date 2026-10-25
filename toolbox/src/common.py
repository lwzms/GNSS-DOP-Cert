import csv,hashlib,importlib.util,json,subprocess
from pathlib import Path,PureWindowsPath
from collections import Counter
class Rejected(Exception):
    def __init__(self,code,detail=''): self.code,self.detail=code,str(detail);super().__init__(code+': '+str(detail))


def need(test,code,detail=''):
    if not test: raise Rejected(code,detail)


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))


def write(p,obj):
    with p.open('x',encoding='utf8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)


def ident(p):return {'path':str(p.resolve()),'sha256':sha(p),'bytes':p.stat().st_size}


def bound(p,digest,role):
    need(p.is_file(),role+'_MISSING',p)
    need(sha(p)==digest,role+'_HASH_MISMATCH',p)
    return ident(p)


def resolve(base,value):
    need(isinstance(value,str) and bool(value),'CONFIG_PATH_INVALID')
    # Local drive absolute or config-root relative only; never probe network paths.
    w=PureWindowsPath(value)
    need(not value.startswith(('\\\\','//')),'UNC_OR_DEVICE_PATH_NOT_ALLOWED',value)
    need(not (w.drive and not w.root),'DRIVE_RELATIVE_PATH_NOT_ALLOWED',value)
    need(not (w.root and not w.drive),'ROOT_RELATIVE_PATH_NOT_ALLOWED',value)
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)],'COM¹','COM²','COM³','LPT¹','LPT²','LPT³'}
    for part in w.parts[1:] if w.anchor else w.parts:
        if part in ('.','..'):continue
        need(not any(c in part for c in '<>:"|?*') and not any(ord(c)<32 for c in part),'PATH_COMPONENT_INVALID',value)
        need(not part.endswith((' ','.')) and part.split('.')[0].upper() not in reserved,'WINDOWS_RESERVED_PATH',value)
    p=Path(value)
    return (p if p.is_absolute() else Path(base)/p).resolve()


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def environment_probe(python,dll):
    # Load and resolve exported symbols only. No setup, epoch or solver calls.
    code="""import sys,platform,struct,json,ctypes,importlib.metadata as m
try: import numpy
except ModuleNotFoundError as e:
    print(json.dumps(dict(dependency_error='NUMPY_MISSING',detail=str(e))));sys.exit(3)
except ImportError as e:
    print(json.dumps(dict(dependency_error='NUMPY_IMPORT_FAILED',detail=str(e))));sys.exit(3)
try: d=ctypes.CDLL(sys.argv[1])
except OSError as e:
    print(json.dumps(dict(dependency_error='DLL_LOAD_FAILED',detail=str(e))));sys.exit(3)
names=json.loads(sys.argv[2])
for name in names:getattr(d,name)
print(json.dumps(dict(implementation=platform.python_implementation(),python=platform.python_version(),bits=struct.calcsize('P')*8,system=platform.system(),numpy=m.version('numpy'),python_full=sys.version,os_version=platform.version(),numpy_path=numpy.__file__,dll_exports=names,native_function_calls=0)))
"""
    try:
        p=subprocess.run([str(python),'-I','-B','-X','utf8','-c',code,str(dll),json.dumps(EXPORTS)],capture_output=True,text=True,encoding='utf8',timeout=20)
        if p.returncode:
            try: failure=json.loads(p.stdout)
            except ValueError: failure={}
            raise Rejected(failure.get('dependency_error','BLOCKED_DEPENDENCY_CONTRACT'),failure.get('detail',p.stderr))
        return json.loads(p.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError) as e:raise Rejected('BLOCKED_DEPENDENCY_CONTRACT',e)


def final_state(q):
    if q['SOLVER_VALID']!='TRUE':return 'SOLVER_FAILURE'
    if any(q[k]!='TRUE' for k in ['OBS_VALID','NAV_VALID','MODEL_VALID']):return 'INVALID_MODEL_OUTPUT'
    return 'VALID_ERROR_SAMPLE' if q['REFERENCE_VALID']=='TRUE' else 'INVALID_REFERENCE'


def qualification_summary(results,quals):
    need(len(results)==len(quals)==40,'REQUEST_COUNT_MISMATCH')
    index={(r['method'],r['gps_ns']):r for r in results}
    need(len(index)==40,'DUPLICATE_REQUEST')
    expected={str(1305254533006000000+i*1000000000) for i in range(20)}
    qi={(r['method'],r['gps_ns']):r for r in quals};need(len(qi)==40 and set(qi)==set(index),'QUALIFICATION_KEYS_MISMATCH')
    for method in ['A','B']:need({k[1] for k in index if k[0]==method}==expected,'SLOT_MISMATCH')
    for key,q in qi.items():
        r=index[key]
        for f in ['OBS_VALID','NAV_VALID','MODEL_VALID','SOLVER_VALID','REFERENCE_VALID']:need(q[f] in ['TRUE','FALSE','UNKNOWN'],'QUALIFICATION_VALUE_INVALID')
        need(type(r['accepted']) is bool and type(r['converged']) is bool,'SOLVER_FLAGS_INVALID')
        need(q['SOLVER_VALID']==('TRUE' if r['accepted'] else 'FALSE'),'ACCEPTED_SOLVER_MISMATCH')
        need(q['FINAL_STATE']==final_state(q),'FINAL_STATE_MISMATCH')
        need(q['REFERENCE_VALID']=='UNKNOWN','REFERENCE_CONTRACT_CHANGED')
        need(q['MODEL_SCOPE']=='FINAL_RESIDUAL_DOMAIN_V1' and q['FULL_PHYSICAL_MODEL_CONTRACT']=='UNKNOWN','MODEL_SCOPE_CHANGED')
    return {m:{'requests':20,'accepted':sum(r['accepted'] for r in results if r['method']==m),'converged':sum(r['converged'] for r in results if r['method']==m),**{f:dict(Counter(q[f] for q in quals if q['method']==m)) for f in ['MODEL_VALID','SOLVER_VALID','REFERENCE_VALID','FINAL_STATE']}} for m in ['A','B']}


def csvrows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


EXPORTS=['setup','set_epoch','run_standard','export_code_terms','start_trace','end_trace','chi_threshold']
