#!/usr/bin/env python3
"""Compose deterministic screening evidence from the existing synthetic display fixture."""

import io
import json
from pathlib import Path
import runpy
import tarfile

runpy.run_path(str(Path(__file__).with_name("make-display-fixture.py")))
with tarfile.open("/tmp/rancher-display-fixture.tar.gz") as archive:
    files = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
prefix = "fixture-node/"
pods = json.loads(files[prefix + "rke2/kubectl/pods.json"])["items"]
pods.append(
    {
        "metadata": {
            "name": "etcd-fixture-node",
            "namespace": "kube-system",
            "uid": "etcd-id",
        },
        "spec": {"nodeName": "fixture-node", "containers": [{"name": "etcd"}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {"name": "etcd", "ready": True, "state": {"running": {}}}
            ],
        },
    }
)
files[prefix + "rke2/kubectl/pods.json"] = json.dumps({"items": pods})
extra = {
    "rke2/kubectl/events.json": json.dumps(
        {
            "items": [
                {
                    "metadata": {"uid": "event-1", "namespace": "business"},
                    "involvedObject": {
                        "kind": "Pod",
                        "name": "app-failed",
                        "uid": "app-failed",
                    },
                    "type": "Warning",
                    "reason": "FailedPull",
                    "message": "synthetic registry denied image",
                    "lastTimestamp": "2026-10-21T10:00:00Z",
                }
            ]
        }
    ),
    "systeminfo/systemd-units": "rke2-server.service loaded active running server\nrke2-agent.service loaded inactive dead agent\n",
    "systeminfo/freeh": "total used free shared buff/cache available\nMem: 8Gi 7Gi 1Mi 1Mi 1Gi 300Mi\nSwap: 0B 0B 0B",
    "systeminfo/vmstat": "r b us sy id wa\n0 0 99 0 1 0\n0 0 1 1 96 2",
    "systeminfo/lscpu": "CPU(s): 4",
    "systeminfo/uptime": "load average: 2.00, 2.00, 2.00",
    "systeminfo/dfh": "Filesystem Size Used Avail Use% Mounted on\n/dev/example 100G 96G 4G 96% /",
    "systeminfo/dfi": "Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/example 10000 1000 9000 10% /",
    "systeminfo/file-nr": "100 0 10000",
    "systeminfo/ps": "USER PID STAT COMMAND\nroot 1 S zombie-named-app\nroot 2 Z dead-process",
    "systeminfo/sysctla": "net.ipv4.ip_forward = 1\nvm.swappiness = 60",
    "rke2/podlogs/kube-system-etcd-fixture-node": "2026-10-21T10:00:00Z apply request took too long\n"
    * 15,
    "etcd/endpointhealth": "https://127.0.0.1:2379 is healthy: successfully committed proposal",
    "etcd/memberlist": "member1, started, fixture-node, https://127.0.0.1:2380, https://127.0.0.1:2379, false",
    "etcd/etcd-metrics-local.txt": "etcd_server_has_leader 1\netcd_mvcc_db_total_size_in_bytes 10\netcd_server_quota_backend_bytes 100",
    "etcd/alarmlist": "",
}
files.update({prefix + k: v for k, v in extra.items()})
with tarfile.open("/tmp/rancher-analysis-fixture.tar.gz", "w:gz") as archive:
    for name, value in files.items():
        raw = value.encode() if isinstance(value, str) else value
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
print("/tmp/rancher-analysis-fixture.tar.gz")
