"""E15 finite-H candidate only. Strict scientific fields; fail-closed certificates."""
import math
from fractions import Fraction as F
from certify import certificate,NAMES
def compare(old,new,left,right):
    if old['identity']!=new['identity']:return {'status':'REJECT','reason':'SOURCE_IDENTITY_MISMATCH'}
    if old['A']!=new['A']:return {'status':'REJECT','reason':'SCIENCE_EXACT_MISMATCH'}
    if not (len(left)==len(right)==len(old['DOP'])==len(new['DOP'])==40):return {'status':'REJECT','reason':'REQUEST_COUNT_MISMATCH'}
    for i,(a,b) in enumerate(zip(left,right)):
        if a['key']!=b['key'] or a['rows']!=b['rows'] or a['H']['float_hex']!=b['H']['float_hex']:return {'status':'REJECT','reason':'FINITE_H_INPUT_MISMATCH'}
        for record in [a,b]:
            for name in ['H','G','Q','diagonal_sums']:
                arr=record[name];vals=arr['values']
                flat=[v for row in vals for v in row] if len(arr['shape'])==2 else vals
                if [float(v).hex() for v in flat]!=arr['float_hex']:return {'status':'REJECT','reason':'ARRAY_BITS_BINDING_MISMATCH'}
        for packet,record in [(old,a),(new,b)]:
            for k,v in zip(NAMES,packet['DOP'][i]):
                if v is None or not math.isfinite(v):return {'status':'REJECT','reason':'NONFINITE_OR_UNDEFINED_DOP'}
                if v.hex()!=record['DOP'][k].hex():return {'status':'REJECT','reason':'OUTPUT_CERTIFICATE_BINDING_MISMATCH'}
        try:
            ca=certificate(a['H']['values'],a['G']['values'],a['Q']['values'],a['DOP'],a['diagonal_sums']['values'])
            cb=certificate(b['H']['values'],b['G']['values'],b['Q']['values'],b['DOP'],b['diagonal_sums']['values'])
        except (ValueError,ZeroDivisionError,OverflowError) as e:return {'status':'REJECT','reason':str(e)}
        if ca['GDOP_gate']!=cb['GDOP_gate']:return {'status':'REJECT','reason':'GDOP_GATE_MISMATCH'}
        for k in NAMES:
            bound=F(ca['fields'][k]['total_absolute_bound']['fraction'])+F(cb['fields'][k]['total_absolute_bound']['fraction'])
            if abs(F.from_float(a['DOP'][k])-F.from_float(b['DOP'][k]))>bound:return {'status':'REJECT','reason':'DOP_BOUND_EXCEEDED'}
    return {'status':'PASS_E15_OFFLINE_CANDIDATE_ONLY','requests':40,'certified_cells':160,'production_authorized':False,'historical_E13_status':'REGRESSION_FAILED'}
