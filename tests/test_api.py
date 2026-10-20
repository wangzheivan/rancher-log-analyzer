import io
from pathlib import Path
import tarfile
from threading import Event
import time
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app
from backend.archive import Cancelled, ImportFailure, extract
from backend.config import Settings
from backend.parsers.bundle import Bundle, PAGE_BYTES, discover, table
from conftest import make_archive, upload


def test_case_and_bundle_lifecycle(client, sample):
    case = client.post('/api/v1/cases', json={'name': '  生产排障  '}).json()
    assert case['name'] == '生产排障'
    assert client.patch('/api/v1/cases/'+case['id'], json={'name': '更新名称'}).json()['name'] == '更新名称'
    records = [upload(client, sample, case_id=case['id']) for _ in range(2)]
    assert all(r['state'] == 'ready' for r in records)
    summary = client.get(f"/api/v1/bundles/{records[0]['id']}/summary").json()
    assert summary['hostname'] == 'node22'
    assert summary['podStatus'] == {'Completed': 1, 'Running': 2}
    assert [p['attention'] for p in summary['pods']] == [False, False, True]
    assert summary['pods'][1]['restartCount'] == 11
    assert summary['nodes'][0]['name'] == 'node22'
    assert 'hello' not in str(summary) # Raw pod logs are never included in summary.
    assert len(client.get('/api/v1/cases').json()[0]['bundles']) == 2
    assert client.delete('/api/v1/bundles/'+records[0]['id']).status_code == 204
    assert client.get(f"/api/v1/bundles/{records[0]['id']}/summary").status_code == 404
    assert client.delete('/api/v1/cases/'+case['id']).status_code == 204
    assert client.get('/api/v1/cases').json() == []
    assert client.get('/api/v1/session').json()['usedBytes'] == 0
    assert list(client.app.state.store.folder.iterdir()) == []


def test_file_access_search_and_binary(client, sample):
    record = upload(client, sample)
    base = f"/api/v1/bundles/{record['id']}"
    files = client.get(base+'/summary').json()['files']
    file = next(f for f in files if f['path'].endswith('kube-run'))
    data = client.get(base+'/files/'+file['id'], params={'q':'error'}).json()
    assert data['lines'] == ['ERROR 中文']
    assert not data['hasMore']
    assert client.get(base+'/files/'+file['id'], params={'q':'absent'}).json()['lines'] == []
    assert client.get(base+'/files/'+file['id'], params={'offset':-1}).status_code == 422
    assert client.get(base+'/files/etc-passwd').status_code == 404
    assert client.get(base+'/files/'+next(f['id'] for f in files if f['path']=='binary')).json()['binary']
    assert client.get(base+'/resources/events').json()['message'] == 'No resources found'
    assert client.get(base+'/resources/nonexistent').status_code == 404
    assert client.get('/api/v1/health').headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize('name,kind', [('../escape',None),('/absolute',None),('C:/windows',None),('a\\b',None),('link',tarfile.SYMTYPE),('hard',tarfile.LNKTYPE),('fifo',tarfile.FIFOTYPE)])
def test_malicious_archives_rejected(client, name, kind):
    record=upload(client, make_archive({name:'bad'},kind))
    assert record['state']=='failed'
    assert client.get('/api/v1/session').json()['usedBytes']==0
    assert not list(client.app.state.store.folder.iterdir())


@pytest.mark.parametrize('setting,value,files', [('unpack_limit',8,{'summary.txt':'longer than eight bytes'}),('session_limit',300,{'summary.txt':'x'*500}),('max_files',1,{'summary.txt':'ok','collector-output.log':'ok'}),('max_depth',2,{'one/two/summary.txt':'ok'})])
def test_import_limits(tmp_path, setting, value, files):
    with TestClient(create_app(Settings(data_dir=tmp_path,**{setting:value}))) as client:
        archive=make_archive(files)
        response=client.post('/api/v1/cases',json={'name':'quota'})
        response=client.post(f"/api/v1/cases/{response.json()['id']}/bundles",params={'filename':'a.tgz'},content=archive)
        if response.status_code==202:
            record_id=response.json()['id']
            for _ in range(200):
                record=client.get('/api/v1/bundles/'+record_id).json()
                if record['state']=='failed':break
                time.sleep(.01)
            assert record['state']=='failed'
        else:
            assert response.status_code==409
        assert client.get('/api/v1/session').json()['usedBytes']==0


def test_upload_limits_and_invalid_input(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path,upload_limit=10))) as client:
        case=client.post('/api/v1/cases',json={'name':'a'}).json()['id']
        assert client.post('/api/v1/cases',json={'name':'   '}).status_code==422
        path=f'/api/v1/cases/{case}/bundles'
        assert client.post(path,params={'filename':'a.zip'},content=b'ok').status_code==400
        assert client.post(path,params={'filename':'a.tgz'},content=b'x'*11).status_code==413
        assert client.post(path,params={'filename':'a.tgz'},content=iter([b'x'*6,b'x'*6])).status_code==413
        assert client.get('/api/v1/session').json()['usedBytes']==0


def test_corrupt_and_multiple_roots(client):
    assert upload(client,b'not a gzip')['state']=='failed'
    assert upload(client,make_archive({'a/summary.txt':'a','b/summary.txt':'b'}))['state']=='failed'
    assert upload(client,make_archive({'random.txt':'no bundle'}))['state']=='failed'


def test_restart_clears_only_owned_session(tmp_path,sample):
    keep=tmp_path/'original.txt';keep.write_text('keep')
    settings=Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert upload(client,sample)['state']=='ready'
    (tmp_path/'session').mkdir();(tmp_path/'session'/'stale').write_text('stale')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/cases').json()==[]
        assert not list((tmp_path/'session').iterdir())
        assert keep.read_text()=='keep'


def test_cancel_queued_and_active_import(client,sample,monkeypatch):
    import backend.store as module
    original=module.extract
    entered,release=Event(),Event()
    def delayed(*args):
        entered.set();release.wait(3)
        return original(*args)
    monkeypatch.setattr(module,'extract',delayed)
    case=client.post('/api/v1/cases',json={'name':'cancel'}).json()['id']
    path=f'/api/v1/cases/{case}/bundles?filename=a.tgz'
    one=client.post(path,content=sample).json()['id'];assert entered.wait(2)
    two=client.post(path,content=sample).json()['id']
    assert client.delete('/api/v1/bundles/'+one).status_code==204
    assert client.delete('/api/v1/bundles/'+two).status_code==204
    release.set()
    for _ in range(200):
        if client.get('/api/v1/session').json()['usedBytes']==0:break
        time.sleep(.01)
    assert client.get('/api/v1/session').json()['usedBytes']==0
    assert not list(client.app.state.store.folder.iterdir())


def test_large_logs_are_bounded_and_paginated(tmp_path):
    (tmp_path/'summary.txt').write_text('Hostname: x')
    text=''.join(f'line {i}\n' for i in range(601))
    (tmp_path/'log').write_text(text)
    (tmp_path/'long').write_bytes(b'a'*(PAGE_BYTES+100)+b'\xfftail\n')
    bundle=Bundle(tmp_path);file_id=next(f['id'] for f in bundle.files if f['path']=='log')
    offset=0;lines=[]
    while True:
        data=bundle.file_page(file_id,offset);lines.extend(data['lines']);assert len(data['lines'])<=250
        assert data['scannedBytes']<=PAGE_BYTES
        if not data['hasMore']:break
        assert data['nextOffset']>offset;offset=data['nextOffset']
    assert lines==text.splitlines()
    long_id=next(f['id'] for f in bundle.files if f['path']=='long')
    data=bundle.file_page(long_id);assert data['hasMore'];assert data['segments'][0]['continued']
    data=bundle.file_page(long_id,data['nextOffset']);assert '�tail' in data['lines'][-1]


def test_json_fallback_and_missing_information(tmp_path):
    (tmp_path/'summary.txt').write_text('Hostname: \nKernel: test')
    kubectl=tmp_path/'rke2/kubectl';kubectl.mkdir(parents=True)
    (kubectl/'nodes.json').write_text('{broken')
    (kubectl/'nodes').write_text('NAME   STATUS   ROLES\nx      Ready    worker\n')
    bundle=Bundle(tmp_path)
    assert bundle.summary['hostname']==''
    assert bundle.summary['nodes'][0]['name']=='x'
    assert len(bundle.warnings)>=2
    assert table('unsupported')['message']
    assert table('NAME   AGE\na      2d\nbad')['skipped']==1


def test_real_sample():
    root=Path(__file__).resolve().parents[1]/'node22-2026-10-20_14_18_53'
    if not root.exists():pytest.skip('local sample not supplied')
    bundle=Bundle(discover(root)[0])
    assert bundle.summary['hostname']=='node22'
    assert bundle.distro=='rke2'
    assert len(bundle.summary['nodes'])==3
    assert len(bundle.files)==284
    assert bundle.summary['podStatus']=={'Running':38,'Completed':13}


def test_gzip_integrity_and_duplicate_paths(client, sample):
    assert upload(client, sample[:-8])['state']=='failed'
    corrupt=bytearray(sample);corrupt[-8]^=255
    assert upload(client,bytes(corrupt))['state']=='failed'
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as archive:
        for _ in range(2):
            item=tarfile.TarInfo('summary.txt');item.size=2;archive.addfile(item,io.BytesIO(b'ok'))
    assert upload(client,out.getvalue())['state']=='failed'
    assert client.get('/api/v1/session').json()['usedBytes']==0


def test_json_pod_priority_and_utf8_boundary(tmp_path):
    import json
    (tmp_path/'summary.txt').write_text('Hostname: test')
    directory=tmp_path/'rke2/kubectl';directory.mkdir(parents=True)
    (directory/'pods').write_text('No resources found')
    (directory/'pods.json').write_text(json.dumps({'items':[{'metadata':{'name':'json-pod','namespace':'test'},'spec':{'containers':[{}]},'status':{'phase':'Running','containerStatuses':[{'ready':True,'restartCount':2}]}}]}))
    content='a'*65535+'中文\n'
    (tmp_path/'unicode.log').write_text(content)
    bundle=Bundle(tmp_path)
    assert bundle.summary['pods'][0]['NAME']=='json-pod'
    file=next(f for f in bundle.files if f['path']=='unicode.log')
    assert ''.join(bundle.file_page(file['id'])['lines'])==content.rstrip('\n')


def test_oversized_extended_header(client):
    # A malicious extended header is rejected before tarfile allocates its declared body.
    item=tarfile.TarInfo('pax');item.type=tarfile.XHDTYPE;item.size=1024*1024*1024
    import gzip
    record=upload(client,gzip.compress(item.tobuf()+b'\0'*1024))
    assert record['state']=='failed'
    assert client.get('/api/v1/session').json()['usedBytes']==0


def test_search_matches_across_segment_and_page_boundaries(tmp_path):
    (tmp_path/'summary.txt').write_text('Hostname: test')
    # Keyword crosses the 64 KiB segment boundary and, separately, the 2 MiB page boundary.
    text='a'*65534+'KEYWORD'+'a'*(PAGE_BYTES-65534-7-2)+'KEYWORD\n'
    (tmp_path/'long.log').write_text(text)
    bundle=Bundle(tmp_path);file=next(f for f in bundle.files if f['path']=='long.log')
    one=bundle.file_page(file['id'],query='keyword')
    assert len(one['lines'])==1
    assert 'KEYWORD' in one['lines'][0]
    assert one['hasMore']
    two=bundle.file_page(file['id'],offset=one['nextOffset'],query='keyword')
    assert len(two['lines'])==1
    assert 'KEYWORD' in two['lines'][0]
    assert two['scannedBytes']<=PAGE_BYTES
