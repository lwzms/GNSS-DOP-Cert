"""Offline NumPy DOP only. No GNSS imports or physical DLL calls."""
import sys,os,json,hashlib,platform,ctypes,argparse
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
FIELDS=('gdop','pdop','hdop','vdop')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):
    with p.open('x',encoding='utf8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def loaded():
    # Windows module enumeration only; never LoadLibrary a GNSS binary.
    k=ctypes.WinDLL('kernel32',use_last_error=True);p=ctypes.WinDLL('psapi',use_last_error=True)
    k.GetCurrentProcess.restype=ctypes.c_void_p
    process=k.GetCurrentProcess();mods=(ctypes.c_void_p*4096)();needed=ctypes.c_ulong()
    p.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong)]
    p.GetModuleFileNameExW.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
    if not p.EnumProcessModules(process,mods,ctypes.sizeof(mods),ctypes.byref(needed)):raise OSError('ENUM_MODULES_FAILED')
    out=[]
    for m in mods[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
        buf=ctypes.create_unicode_buffer(32768)
        if p.GetModuleFileNameExW(process,m,buf,len(buf)):
            path=Path(buf.value)
            out.append({'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size})
    assert not any('rtklib' in x['path'].lower() or 'gnss-return' in x['path'].lower() for x in out)
    return out
def environment():
    core=np._core._multiarray_umath
    return {'utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'executable':sys.executable,'executable_sha256':sha(sys.executable),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'sys_path':sys.path,'numpy':np.__version__,'numpy_file':np.__file__,'numpy_config':np.__config__.CONFIG,'platform':platform.platform(),'machine':platform.machine(),'environment':{k:v for k,v in os.environ.items() if k in ['PATH','PYTHONPATH','PYTHONHOME','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE','TEMP','TMP'] or k.startswith(('MKL','OPENBLAS','OMP','NPY'))},'cpu_features':getattr(core,'__cpu_features__',{}),'cpu_baseline':getattr(core,'__cpu_baseline__',[]),'cpu_dispatch':getattr(core,'__cpu_dispatch__',[]),'loaded_binaries':loaded(),'imported_modules':{k:str(getattr(v,'__file__',None)) for k,v in sys.modules.items() if getattr(v,'__file__',None)},'GNSS_DLL_loaded':False}
def array(out,i,name,a):
    a=np.asarray(a);file=f'{i:02d}_{name}.npy';np.save(out/file,a,allow_pickle=False)
    return {'file':file,'sha256':sha(out/file),'shape':list(a.shape),'dtype':a.dtype.str,'byteorder':a.dtype.byteorder,'C_order':bool(a.flags.c_contiguous),'values':a.tolist(),'float_hex':[float(x).hex() for x in a.flat],'raw_C_sha256':hashlib.sha256(a.tobytes(order='C')).hexdigest()}
def tail(Q):
    d=np.diag(Q)
    sums=[sum(d),sum(d[:3]),sum(d[:2]),d[2]]
    return sums, [float(np.sqrt(s)) for s in sums]
def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['angles','H','G','Q'],required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    inp=json.loads(a.inputs.read_text(encoding='utf8'))['E12'];records=[];counts={'trig_design':0,'Gram':0,'inverse':0,'rank':0,'svd_diagnostic':0,'DOP_tail':0,'navigation':0}
    for i,row in enumerate(inp):
        rec={'key':row['key'],'source_epoch_index':row['source_epoch_index'],'rows':[n for n in row['nodes'] if n['used']]}
        if a.mode=='angles':
            angles=np.array([[float(t['az_raw']),float(t['el_raw'])] for t in rec['rows']]);az,e=angles.T
            H=np.c_[np.cos(e)*np.sin(az),np.cos(e)*np.cos(az),np.sin(e),np.ones(len(e))]
            rec['angles']=array(a.out,i,'angles',angles);counts['trig_design']+=1
        elif a.mode=='H':H=np.load(a.source/f'{i:02d}_H.npy',allow_pickle=False)
        elif a.mode=='G':G=np.load(a.source/f'{i:02d}_G.npy',allow_pickle=False)
        else:Q=np.load(a.source/f'{i:02d}_Q.npy',allow_pickle=False)
        if a.mode in ['angles','H']:
            rank=int(np.linalg.matrix_rank(H));counts['rank']+=1
            rec['rank']=rank;rec['H']=array(a.out,i,'H',H)
            if rank!=4:raise ValueError('RANK_NOT_FOUR')
            G=H.T@H;counts['Gram']+=1
        if a.mode!='Q':
            rec['G']=array(a.out,i,'G',G);Q=np.linalg.inv(G);counts['inverse']+=1
        rec['Q']=array(a.out,i,'Q',Q)
        sums,dop=tail(Q);counts['DOP_tail']+=1
        rec['diagonal_sums']=array(a.out,i,'sums',np.asarray(sums));rec['DOP']=dict(zip(FIELDS,dop));rec['DOP_hex']={k:v.hex() for k,v in rec['DOP'].items()}
        if a.mode in ['angles','H']:
            sv=np.linalg.svd(H,compute_uv=False);counts['svd_diagnostic']+=1;rec['singular_values']=sv.tolist();rec['condition_H']=float(sv[0]/sv[-1])
        records.append(rec)
    dump(a.out/'records.json',records);dump(a.out/'environment.json',environment());dump(a.out/'counts.json',counts)
    print(json.dumps({'status':'COMPLETED','mode':a.mode,'requests':len(records),'counts':counts}))
if __name__=='__main__':main()
