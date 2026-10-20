#!/usr/bin/env python3
"""Create a small synthetic bundle for repeatable browser tests."""
import io
import tarfile
files={
    'summary.txt':'Hostname: fixture-node\nGenerated: fixture-time\nDistro: rke2\n',
    'collector-output.log':'ok',
    'rke2/kubectl/pods':'No resources found\n',
    'test.log':'<script>window.pwned=1</script>\n'+''.join(f'line {i}\n' for i in range(1,600))+'ONLY-AT-END\n',
}
with tarfile.open('/tmp/rancher-ui-fixture.tar.gz','w:gz') as archive:
    for name,value in files.items():
        raw=value.encode();info=tarfile.TarInfo(name);info.size=len(raw)
        archive.addfile(info,io.BytesIO(raw))
print('/tmp/rancher-ui-fixture.tar.gz')
