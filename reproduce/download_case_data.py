"""Explicitly download and hash-check the two fixed raw inputs; no GNSS parsing."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCES=ROOT/'reproduce/environment/data_download_identity.json'

def extract_verified(raw, source):
    if hashlib.sha256(raw).hexdigest()!=source['archive_sha256']:
        raise ValueError('ARCHIVE_HASH_MISMATCH:'+source['role'])
    if source['role']=='OBS':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if source['member'] not in archive.namelist():raise ValueError('OBS_MEMBER_MISSING')
            if archive.getinfo(source['member']).file_size!=source['bytes']:raise ValueError('OBS_SIZE_MISMATCH')
            content=archive.read(source['member'])
    elif source['role']=='NAV':
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:content=f.read(source['bytes']+1)
    else:raise ValueError('UNKNOWN_ROLE')
    if len(content)!=source['bytes'] or hashlib.sha256(content).hexdigest()!=source['sha256']:
        raise ValueError('INPUT_HASH_MISMATCH:'+source['role'])
    return content

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination',required=True,type=Path,help='New data directory outside the repository')
    args=p.parse_args();dest=args.destination.resolve()
    if dest.is_relative_to(ROOT) or dest.exists():raise ValueError('NEW_EXTERNAL_DIRECTORY_REQUIRED')
    sources=json.loads(SOURCES.read_text())['sources']
    contents=[]
    for s in sources:
        request=urllib.request.Request(s['url'],headers={'User-Agent':'GNSS118-fixed-input-download'})
        with urllib.request.urlopen(request,timeout=90) as response:
            raw=response.read(s['archive_bytes']+1)
        contents.append((s,extract_verified(raw,s)))
    # No output is created until both complete files meet their frozen identities.
    dest.mkdir(parents=True,exist_ok=False)
    receipt=[]
    for s,content in contents:
        with (dest/s['filename']).open('xb') as f:f.write(content)
        receipt.append({'role':s['role'],'filename':s['filename'],'sha256':s['sha256'],'bytes':len(content),'source_url':s['url']})
    (dest/'download_receipt.json').write_text(json.dumps({'status':'HASH_MATCHED','files':receipt,'navigation_calls':0},indent=2)+'\n')
    print(json.dumps({'status':'HASH_MATCHED','files':2,'navigation_calls':0}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'FAILED','reason':str(exc),'navigation_calls':0}));raise SystemExit(2)
