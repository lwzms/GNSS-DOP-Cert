"""Exact finite-input certificates, independent of NumPy arithmetic."""
import json,hashlib,math,csv
from fractions import Fraction as F
from pathlib import Path
B=Path(__file__).resolve().parent;R=B/'runs/fixed_input_dop_replay_01'
JOBS=['A_angles','B_angles','AB','BA','GA','GB','QA','QB'];NAMES=['gdop','pdop','hdop','vdop'];INDICES=[[0,1,2,3],[0,1,2],[0,1],[2]]
def load(p):return json.loads(p.read_text(encoding='utf8'))
def save(p,v):
    with p.open('x',encoding='utf8') as f:json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False)
def ff(x):return F.from_float(x)
def mat(x):return [[ff(v) for v in row] for row in x]
def mul(a,b):return [[sum((x*y for x,y in zip(row,col)),F()) for col in zip(*b)] for row in a]
def transpose(x):return list(map(list,zip(*x)))
def norm(x):return max(sum(map(abs,row),F()) for row in x)
def minus(a,b):return [[x-y for x,y in zip(u,v)] for u,v in zip(a,b)]
def inverse(a):
    n=len(a);m=[row[:]+[F(i==j) for j in range(n)] for i,row in enumerate(a)]
    for i in range(n):
        k=next((k for k in range(i,n) if m[k][i]),None)
        if k is None:raise ValueError('EXACT_RANK_DEFICIENT')
        m[i],m[k]=m[k],m[i];d=m[i][i];m[i]=[v/d for v in m[i]]
        for j in range(n):
            if j!=i:
                d=m[j][i];m[j]=[x-d*y for x,y in zip(m[j],m[i])]
    return [row[n:] for row in m]
def sqrt_interval(s):
    if s<0:raise ValueError('NONPOSITIVE_DIAGONAL_SUM')
    scale=10**80;q=math.isqrt(s.numerator*scale*scale//s.denominator)
    lo=F(q,scale);hi=lo if lo*lo==s else F(q+1,scale)
    assert lo*lo<=s<=hi*hi
    return lo,hi
def obj(f):return {'fraction':str(f),'display':float(f)}
def interval(v):return {'lower':str(v[0]),'upper':str(v[1]),'lower_display':float(v[0]),'upper_display':float(v[1])}
def error(v,it):return max(abs(v-it[0]),abs(v-it[1]))
def certificate(h,g,q,dop,sums):
    if not all(math.isfinite(v) for a in [h,g,q] for row in a for v in row) or not all(math.isfinite(v) for v in list(dop.values())+sums):raise ValueError('NONFINITE_INPUT')
    H,G,Q=mat(h),mat(g),mat(q);exactG=mul(transpose(H),H);exactQ=inverse(exactG)
    I=[[F(i==j) for j in range(4)] for i in range(4)];rho=norm(minus(I,mul(exactG,Q)))
    if rho>=1:raise ValueError('RESIDUAL_BOUND_NOT_CERTIFIED')
    bound=norm(Q)*rho/(1-rho);actualQ=norm(minus(Q,exactQ));assert actualQ<=bound
    fields={}
    for k,idx,s in zip(NAMES,INDICES,sums):
        tr=sum((exactQ[j][j] for j in idx),F());est=sum((Q[j][j] for j in idx),F())
        if min(tr,est,ff(s))<=0:raise ValueError('NONPOSITIVE_DIAGONAL_SUM')
        # Independently verify every binary64 addition and the sqrt rounding cell.
        sequential=0.0
        for j in idx:sequential=float(ff(sequential)+Q[j][j])
        if sequential.hex()!=s.hex():raise ValueError('SUM_ROUNDING_NOT_CERTIFIED')
        value=dop[k]
        lowmid=(ff(math.nextafter(value,-math.inf))+ff(value))/2
        highmid=(ff(value)+ff(math.nextafter(value,math.inf)))/2
        if not (value>0 and lowmid*lowmid<=ff(s)<=highmid*highmid):raise ValueError('SQRT_ROUNDING_NOT_CERTIFIED')
        # Midpoint ties would need an explicit even-significand check.
        if ff(s) in (lowmid*lowmid,highmid*highmid):raise ValueError('SQRT_TIE_REQUIRES_CHECK')
        radius=len(idx)*bound
        if est-radius<=0:raise ValueError('POSTERIOR_SQRT_NOT_CERTIFIED')
        ref=sqrt_interval(tr);qroot=sqrt_interval(est);sroot=sqrt_interval(ff(s))
        posterior=(sqrt_interval(est-radius)[0],sqrt_interval(est+radius)[1])
        # Exact finite sums; reference root brackets from integer square roots.
        inverse_effect=max(abs(qroot[1]-posterior[0]),abs(posterior[1]-qroot[0]))
        sum_effect=max(abs(qroot[0]-sroot[1]),abs(qroot[1]-sroot[0]))
        sqrt_effect=error(ff(dop[k]),sroot)
        total=inverse_effect+sum_effect+sqrt_effect
        actual=error(ff(dop[k]),ref)
        assert actual<=total
        fields[k]={'reference':interval(ref),'posterior_reference':interval(posterior),'sum_rounding':obj(abs(ff(s)-est)),'sum_rounding_certified':True,'sqrt_rounding_certified':True,'sqrt_rounding_bound':obj(sqrt_effect),'inverse_propagation_bound':obj(inverse_effect),'sum_propagation_bound':obj(sum_effect),'total_absolute_bound':obj(total),'actual_absolute_error_upper':obj(actual),'relative_error_upper':obj(actual/ref[0]),'output':dop[k],'output_hex':dop[k].hex(),'bound_covers_actual':True}
    gd=fields['gdop']['posterior_reference'];lo,hi=F(gd['lower']),F(gd['upper'])
    gate='VALID' if 0<lo<=hi<=30 else 'INVALID_ABOVE_30' if lo>30 else 'UNCERTAIN'
    if gate=='UNCERTAIN':raise ValueError('GDOP_GATE_NOT_CERTIFIED')
    return {'status':'CERTIFIED_E15_FINITE_H','exact_rank':4,'gram_error_inf':obj(norm(minus(G,exactG))),'inverse_error_inf':obj(actualQ),'rho':obj(rho),'inverse_posterior_bound_inf':obj(bound),'fields':fields,'GDOP_gate':gate,'exact_Gram':[[str(v) for v in row] for row in exactG],'exact_Q':[[str(v) for v in row] for row in exactQ]}
def main():
    data={j:load(R/j/'records.json') for j in JOBS};inp=load(R/'inputs.json')
    comparisons=[]
    for a,b in [('A_angles','B_angles'),('A_angles','AB'),('BA','B_angles'),('GA','GB'),('QA','QB')]:
        for field in ['angles','H','G','Q','diagonal_sums','DOP']:
            if field not in data[a][0] or field not in data[b][0]:continue
            cells=rows=0;mx=0;den=0
            for x,y in zip(data[a],data[b]):
                if field=='DOP':u=[x[field][k] for k in NAMES];v=[y[field][k] for k in NAMES]
                else:u=[float.fromhex(z) for z in x[field]['float_hex']];v=[float.fromhex(z) for z in y[field]['float_hex']]
                changed=sum(p.hex()!=q.hex() for p,q in zip(u,v));cells+=changed;rows+=bool(changed);den+=len(u);mx=max(mx,max(abs(p-q) for p,q in zip(u,v)))
            comparisons.append({'left':a,'right':b,'field':field,'changed_requests':rows,'changed_cells':cells,'cells':den,'max_abs_difference':mx})
    replay={}
    for j,old in [('A_angles','E12'),('B_angles','E13')]:
        diff=[{'key':x['key'],'field':k,'new':x['DOP'][k],'old':y['DOP'][k]} for x,y in zip(data[j],inp[old]) for k in NAMES if x['DOP'][k].hex()!=y['DOP'][k].hex()]
        replay[j]={'compared':160,'differences':diff,'status':'OFFLINE_DOP_OUTPUT_REPLAY_MATCHED' if not diff else 'MISMATCH'}
    certs={};stats={};outcsv=[]
    for j in JOBS:
        cc=[]
        for i,r in enumerate(data[j]):
            h=data['B_angles' if j in ['BA','B_angles'] else 'A_angles'][i]['H']['values']
            g=r.get('G',data['A_angles'][i]['G'])['values'];q=r['Q']['values']
            c=certificate(h,g,q,r['DOP'],r['diagonal_sums']['values']);c.update(key=r['key'],source_epoch_index=r['source_epoch_index'],H_raw_sha256=data['A_angles'][i]['H']['raw_C_sha256'])
            cc.append(c)
            outcsv.append({'job':j,'key':'/'.join(r['key']),'index':r['source_epoch_index'],'rho':float(F(c['rho']['fraction'])),'inverse_bound':c['inverse_posterior_bound_inf']['display'],'GDOP':r['DOP']['gdop'],'GDOP_gate':c['GDOP_gate'],'gdop_error_upper':c['fields']['gdop']['actual_absolute_error_upper']['display'],'gdop_bound':c['fields']['gdop']['total_absolute_bound']['display']})
        certs[j]=cc
        stats[j]={'certified':len(cc),'gate_valid':sum(c['GDOP_gate']=='VALID' for c in cc),'gate_above30':sum(c['GDOP_gate']=='INVALID_ABOVE_30' for c in cc),'max_rho':max(c['rho']['display'] for c in cc),'max_Gram_error_inf':max(c['gram_error_inf']['display'] for c in cc),'max_Q_error_inf':max(c['inverse_error_inf']['display'] for c in cc),'max_Q_bound_inf':max(c['inverse_posterior_bound_inf']['display'] for c in cc),'max_DOP_error_upper':max(c['fields'][k]['actual_absolute_error_upper']['display'] for c in cc for k in NAMES),'max_DOP_bound':max(c['fields'][k]['total_absolute_bound']['display'] for c in cc for k in NAMES)}
    paircert=[]
    for i,(a,b) in enumerate(zip(certs['A_angles'],certs['B_angles'])):
        assert data['A_angles'][i]['H']['float_hex']==data['B_angles'][i]['H']['float_hex']
        for k in NAMES:
            bound=F(a['fields'][k]['total_absolute_bound']['fraction'])+F(b['fields'][k]['total_absolute_bound']['fraction']);delta=abs(ff(a['fields'][k]['output'])-ff(b['fields'][k]['output']))
            assert delta<=bound and a['GDOP_gate']==b['GDOP_gate']
            paircert.append({'key':a['key'],'field':k,'difference':obj(delta),'bound':obj(bound),'covered':True})
    summary={'replay':replay,'stage_comparisons':comparisons,'certificates':stats,'pair_bounds_covered':len(paircert),'H_condition_range':[min(r['condition_H'] for r in data['A_angles']),max(r['condition_H'] for r in data['A_angles'])],'smallest_singular_value':min(r['singular_values'][-1] for r in data['A_angles']),'source':'E15 fixed binary64 H only; historical H not certified','status':'E15_FIXED_INPUT_NUMERICAL_CAUSE_SUPPORTED' if all(not x['differences'] for x in replay.values()) else 'E15_OFFLINE_REPLAY_MISMATCH'}
    save(R/'certificates.json',certs);save(R/'pair_certificates.json',paircert);save(R/'numerical_summary.json',summary)
    with (R/'certificate_summary.csv').open('x',newline='',encoding='utf8') as f:w=csv.DictWriter(f,fieldnames=outcsv[0]);w.writeheader();w.writerows(outcsv)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
