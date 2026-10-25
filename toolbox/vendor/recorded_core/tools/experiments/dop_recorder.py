"""Capture already-computed DOP arrays; no matrix products, inverse or decisions."""
import json,hashlib,sys,os,ctypes,platform
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    with Path(p).open('x',encoding='utf8') as f:json.dump(x,f,indent=2,ensure_ascii=False,allow_nan=False)
def runtime():
    k=ctypes.WinDLL('kernel32');p=ctypes.WinDLL('psapi');k.GetCurrentProcess.restype=ctypes.c_void_p
    proc=k.GetCurrentProcess();mods=(ctypes.c_void_p*4096)();needed=ctypes.c_ulong()
    p.EnumProcessModules.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong)]
    p.GetModuleFileNameExW.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
    if not p.EnumProcessModules(proc,mods,ctypes.sizeof(mods),ctypes.byref(needed)):raise OSError('MODULE_ENUMERATION_FAILED')
    binaries=[]
    for m in mods[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
        text=ctypes.create_unicode_buffer(32768)
        if p.GetModuleFileNameExW(proc,m,text,len(text)):binaries.append({'path':text.value,'sha256':sha(text.value)})
    return {'utc':datetime.now(timezone.utc).isoformat(),'executable':sys.executable,'python_sha256':sha(sys.executable),'python':sys.version,'numpy':np.__version__,'numpy_file':np.__file__,'numpy_config':np.__config__.CONFIG,'sys_path':sys.path,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'platform':platform.platform(),'cpu_features':np._core._multiarray_umath.__cpu_features__,'environment':{k:v for k,v in os.environ.items() if k in ['PATH','TEMP','TMP','PYTHONPATH','PYTHONHOME','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE'] or k.startswith(('MKL','OMP','OPENBLAS','NPY'))},'loaded_binaries':binaries,'modules':{k:str(v.__file__) for k,v in list(sys.modules.items()) if getattr(v,'__file__',None)}}
class Recorder:
    def __init__(self,root,source):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False);self.source=Path(source).resolve();self.source_sha=sha(self.source);self.keys=set();self.records=[]
        write(self.root/'runtime_start.json',runtime());self.runtime_sha=sha(self.root/'runtime_start.json')
    def array(self,folder,name,value):
        original=np.asarray(value)
        if not np.all(np.isfinite(original)):raise ValueError('NONFINITE_RECORD_ARRAY')
        # Copy and disable writes on the copy only; do not mutate caller flags.
        copy=np.array(original,copy=True,order='K');copy.setflags(write=False)
        if np.shares_memory(original,copy):raise ValueError('RECORDER_ARRAY_ALIAS')
        p=folder/(name+'.npy')
        with p.open('xb') as f:np.save(f,copy,allow_pickle=False)
        return {'file':p.name,'sha256':sha(p),'dtype':copy.dtype.str,'shape':list(copy.shape),'byteorder':copy.dtype.byteorder,'values':copy.tolist(),'float_hex':[float(v).hex() for v in copy.flat],'raw_C_sha256':hashlib.sha256(copy.tobytes(order='C')).hexdigest(),'copy_writeable':bool(copy.flags.writeable),'shares_memory':False}
    def capture(self,rec,good,angles,H,rank,G,Q,d,sums,reason=None):
        key=(str(rec['gps_ns']),rec['method']);rid=key[1]+'_'+key[0]
        if key in self.keys:raise ValueError('DUPLICATE_DOP_REQUEST')
        self.keys.add(key);folder=self.root/rid;folder.mkdir(exist_ok=False)
        out={'request_id':rid,'key':list(key),'gps_time_ns':key[0],'method':key[1],'source_epoch_index':rec.get('source_epoch_index'),'used_satellite_order':[t['sv'] for t in good],'original_az_el_strings':[[t['az_rad'],t['el_rad']] for t in good],'rows':[{'row':i,'sv':t['sv'],'az_raw':t['az_rad'],'el_raw':t['el_rad']} for i,t in enumerate(good)],'rank':rank,'DOP':{k:rec.get(k) for k in ['gdop','pdop','hdop','vdop']},'dop_defined_or_undefined':'DEFINED' if Q is not None else 'UNDEFINED','reason':reason or (None if Q is not None else 'RANK_BELOW_FOUR_OR_NO_GOOD_ROWS'),'production_source_path':str(self.source),'production_source_hash':self.source_sha,'numpy_runtime_identity':{'start_file':'../runtime_start.json','start_sha256':self.runtime_sha,'end_binding':'recording_seal.json -> runtime_end.json'}}
        for name,arr in [('angles',angles),('H',H),('G',G),('Q',Q),('Q_diagonal',d),('diagonal_sums',sums)]:
            out[name]=None if arr is None else self.array(folder,name,arr)
        out['DOP_hex']={k:None if v is None else float(v).hex() for k,v in out['DOP'].items()}
        write(folder/'record.json',out);self.records.append({'key':list(key),'file':rid+'/record.json','sha256':sha(folder/'record.json')})
    def unavailable(self,rec,reason):self.capture(rec,[],None,None,None,None,None,None,None,reason)
    def finish(self):
        write(self.root/'runtime_end.json',runtime())
        if sha(self.source)!=self.source_sha:raise ValueError('PRODUCTION_SOURCE_CHANGED')
        files=[{'path':p.relative_to(self.root).as_posix(),'sha256':sha(p)} for p in sorted(self.root.rglob('*')) if p.is_file()]
        write(self.root/'recording_seal.json',{'version':'E16_PRODUCTION_DOP_RECORD_V1','complete':True,'recorded_requests':len(self.records),'records':self.records,'files':files,'source_sha256':self.source_sha})
def verify(root,expected=None):
    root=Path(root);seal=json.loads((root/'recording_seal.json').read_text(encoding='utf8'))
    if not seal['complete']:raise ValueError('RECORDING_NOT_COMPLETE')
    listed={r['path'] for r in seal['files']};actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='recording_seal.json'}
    if listed!=actual:raise ValueError('RECORDING_INVENTORY_MISMATCH')
    for f in seal['files']:
        p=(root/f['path']).resolve()
        if not p.is_relative_to(root.resolve()) or sha(p)!=f['sha256']:raise ValueError('RECORDING_HASH_MISMATCH')
    records=[]
    for x in seal['records']:
        p=root/x['file'];r=json.loads(p.read_text(encoding='utf8'))
        if sha(p)!=x['sha256'] or r['key']!=x['key']:raise ValueError('RECORD_KEY_MISMATCH')
        for name in ['angles','H','G','Q','Q_diagonal','diagonal_sums']:
            a=r[name]
            if a is None:
                if r['dop_defined_or_undefined']=='DEFINED':raise ValueError('DEFINED_RECORD_ARRAY_MISSING')
                continue
            arr=np.load(p.parent/a['file'],allow_pickle=False)
            if sha(p.parent/a['file'])!=a['sha256'] or [float(v).hex() for v in arr.flat]!=a['float_hex'] or list(arr.shape)!=a['shape'] or arr.dtype.str!=a['dtype']:raise ValueError('ARRAY_IDENTITY_MISMATCH')
        records.append(r)
    if len({tuple(r['key']) for r in records})!=len(records) or len(records)!=seal['recorded_requests']:raise ValueError('RECORD_COUNT_MISMATCH')
    if expected is not None and len(records)!=expected:raise ValueError('RECORD_COUNT_MISMATCH')
    return records
