import io
from pathlib import Path
import tarfile
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings


def make_archive(files, kind=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, value in files.items():
            info = tarfile.TarInfo(name)
            if kind:
                info.type = kind
                info.linkname = '/etc/passwd'
            else:
                value = value.encode() if isinstance(value, str) else value
                info.size = len(value)
            archive.addfile(info, None if kind else io.BytesIO(value))
    return output.getvalue()


@pytest.fixture
def sample():
    return make_archive({'outer/node/summary.txt': 'Hostname:  node22\nDistro:    rke2\nGenerated: sample time\nKernel: test\nPRETTY_NAME="Ubuntu"\n',
        'outer/node/collector-output.log': 'ok', 'outer/node/versions': 'rke2 version v1.34.11+rke2r1',
        'outer/node/rke2/kubectl/nodes': 'NAME     STATUS   ROLES    AGE   VERSION\nnode22   Ready    worker   26d   v1.34\n',
        'outer/node/rke2/kubectl/pods': 'NAMESPACE   NAME   READY   STATUS      RESTARTS         AGE   IP         NODE\nkube        done   0/1     Completed   2                26d   1.2.3.4    node22\nkube        run    1/1     Running     11 (2d ago)      26d   1.2.3.5    node22\nkube        bad    0/1     Running     0                26d   1.2.3.6    node22\n',
        'outer/node/rke2/kubectl/events': 'No resources found\n',
        'outer/node/rke2/podlogs/kube-run': 'INFO hello\nERROR 中文\n<script>window.pwned=1</script>\n',
        'outer/node/binary': b'\x00\x01\x02'})


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        yield client


def upload(client, archive, name='node.tar.gz', case_id=None):
    if case_id is None:
        case_id = client.post('/api/v1/cases', json={'name': '测试案例'}).json()['id']
    response = client.post(f'/api/v1/cases/{case_id}/bundles', params={'filename': name}, content=archive)
    assert response.status_code == 202, response.text
    record = response.json()
    for _ in range(200):
        record = client.get('/api/v1/bundles/' + record['id']).json()
        if record['state'] in ('ready', 'failed'):
            return record
        time.sleep(.01)
    raise AssertionError('import timed out')
