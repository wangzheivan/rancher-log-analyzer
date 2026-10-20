#!/usr/bin/env python3
"""Verify NodePort and in-place container restart on an otherwise empty test workspace."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',required=True)
parser.add_argument('--context',required=True)
parser.add_argument('--node-url',action='append',default=[],help='Additional reachable NodePort base URL; repeat for multiple nodes')
parser.add_argument('--archive',default='/tmp/rancher-sample.tar.gz')
args=parser.parse_args()
command=['kubectl','--context',args.context,'--request-timeout=15s','--namespace','rancher-log-analyzer']

def pods():
    data=json.loads(subprocess.check_output(command+['get','pods','-l','app.kubernetes.io/instance=rancher-log-analyzer','-o','json']))
    return data['items'][0]

with httpx.Client(base_url=args.base_url,timeout=90,trust_env=False) as client:
    node_urls=list(dict.fromkeys([args.base_url]+args.node_url))
    for node_url in node_urls:
        response=client.get(node_url.rstrip('/')+'/api/v1/health');response.raise_for_status()
        assert response.json()['status']=='ok'
    if client.get('/api/v1/cases').json():
        raise SystemExit('Workspace is not empty. Restart verification refused to protect existing cases.')
    case=client.post('/api/v1/cases',json={'name':'临时重启验收'});case.raise_for_status();case_id=case.json()['id']
    with open(args.archive,'rb') as stream:
        response=client.post(f'/api/v1/cases/{case_id}/bundles?filename=real-sample.tar.gz',content=stream,headers={'Content-Type':'application/gzip'})
    response.raise_for_status();bundle_id=response.json()['id']
    for _ in range(180):
        record=client.get(f'/api/v1/bundles/{bundle_id}').json()
        if record['state'] in ('ready','failed'):break
        time.sleep(.5)
    assert record['state']=='ready',record
    summary=client.get(f'/api/v1/bundles/{bundle_id}/summary').json()
    assert summary['files'], 'Expected at least one collected file'
    assert client.get('/api/v1/session').json()['usedBytes']>0
    # Avoid clearing any case that another visitor created during the upload.
    assert {c['id'] for c in client.get('/api/v1/cases').json()}=={case_id},'Another case appeared; restart skipped'
    before=pods();restarts=before['status']['containerStatuses'][0]['restartCount']
    subprocess.run(command+['exec',before['metadata']['name'],'--','python','-c','import os,signal; os.kill(1, signal.SIGTERM)'],check=True)
    for _ in range(120):
        current=pods();status=current['status']['containerStatuses'][0]
        if status['restartCount']>restarts and status.get('ready'):
            try:
                result=client.get('/api/v1/health')
                if result.status_code==200:break
            except httpx.TransportError:
                pass
        time.sleep(1)
    else:
        raise AssertionError('container did not restart successfully')
    assert current['metadata']['uid']==before['metadata']['uid'],'Expected in-place container restart'
    assert client.get('/api/v1/cases').json()==[]
    assert client.get('/api/v1/session').json()['usedBytes']==0
    result={'nodePorts':node_urls,
        'image':current['spec']['containers'][0]['image'],'pod':current['metadata']['name'],
        'samePodContainerRestart':True,'restartCount':status['restartCount'],'sessionCleared':True,
        'sample':{'nodes':len(summary['nodes']),'pods':len(summary['pods']),'files':len(summary['files'])}}
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/cluster-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
