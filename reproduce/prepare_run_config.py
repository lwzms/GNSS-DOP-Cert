"""Create a new fixed-case config with local paths; never invokes the DLL."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def create(work, run_id, inputs):
    work=Path(work).resolve()
    if work.is_relative_to(ROOT) or work.exists():raise ValueError('NEW_EXTERNAL_WORK_DIRECTORY_REQUIRED')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',run_id):raise ValueError('INVALID_RUN_ID')
    if platform.system()!='Windows' or struct.calcsize('P')*8!=64 or platform.python_version()!='3.13.5':
        raise ValueError('REQUIRES_WINDOWS_64_CPYTHON_3_13_5')
    import numpy as np
    if np.__version__!='2.1.3':raise ValueError('REQUIRES_NUMPY_2_1_3')
    build=np.show_config(mode='dicts')
    if 'mkl' not in json.dumps(build.get('Build Dependencies',{})).lower():raise ValueError('REQUIRES_DECLARED_MKL_BUILD')
    config=json.loads((ROOT/'toolbox/config.template.json').read_text())
    for role, location in inputs.items():
        p=Path(location).resolve()
        if not p.is_file():raise ValueError(role.upper()+'_MISSING:'+str(p))
        if digest(p)!=config['inputs'][role]['sha256']:raise ValueError(role.upper()+'_HASH_MISMATCH')
        config['inputs'][role]['path']=str(p)
    exe=Path(sys.executable).resolve()
    config['python']['path']=str(exe);config['python']['sha256']=digest(exe)
    config['run_id']=run_id
    work.mkdir(parents=True,exist_ok=False)
    (work/'config.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'CONFIG_CREATED','config':str(work/'config.json'),'navigation_calls':0,'next':'Run public toolbox preflight, then explicitly decide whether to run navigation.'}))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['obs','nav','dll','work-dir','run-id']:p.add_argument('--'+arg,required=True)
    a=p.parse_args();create(a.work_dir,a.run_id,{k:getattr(a,k) for k in ['obs','nav','dll']})

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'FAILED','reason':str(exc),'navigation_calls':0}));raise SystemExit(2)
