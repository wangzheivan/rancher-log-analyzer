#!/usr/bin/env python3
"""Create portable synthetic metadata and nested logs without production data."""
import argparse
import io
import json
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument("--pods", type=int, default=10000)
parser.add_argument("--nodes", type=int, default=300)
parser.add_argument("--output", default="/tmp/rancher-scale.tar.gz")
args = parser.parse_args()
pods = []
for i in range(args.pods):
    pods.append(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"app-{i:05d}",
                "namespace": f"ns-{i%100:03d}",
                "uid": f"uid-{i}",
                "labels": {"app": "fixture"},
            },
            "spec": {
                "nodeName": f"node-{i%args.nodes:03d}",
                "containers": [
                    {
                        "name": "web",
                        "image": "example/web:1",
                        "resources": {"requests": {"cpu": "100m", "memory": "32Mi"}},
                        "readinessProbe": {"httpGet": {"path": "/", "port": 80}},
                        "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                    }
                ],
                "initContainers": [{"name": "init", "image": "example/init:1"}],
            },
            "status": {
                "phase": "Succeeded" if i == 1 else "Running",
                "podIP": "192.0.2.10",
                "containerStatuses": [
                    {
                        "name": "web",
                        "ready": i != 1,
                        "restartCount": 4,
                        "state": {"running": {}},
                    }
                ],
            },
        }
    )
nodes = [
    {
        "metadata": {"name": f"node-{i:03d}", "uid": f"node-uid-{i}"},
        "status": {
            "capacity": {"cpu": "8", "memory": "16Gi"},
            "allocatable": {"cpu": "7", "memory": "15Gi"},
            "conditions": [{"type": "Ready", "status": "True"}],
            "addresses": [{"type": "InternalIP", "address": "192.0.2.10"}],
            "nodeInfo": {"kubeletVersion": "v1.34", "osImage": "Synthetic Linux"},
        },
    }
    for i in range(args.nodes)
]
files = {
    "summary.txt": "Hostname: node-000\nGenerated: synthetic-time\nDistro: rke2\n",
    "collector-output.log": "synthetic fixture",
    "rke2/kubectl/pods.json": json.dumps({"items": pods}),
    "rke2/kubectl/nodes.json": json.dumps({"items": nodes}),
    "rke2/kubectl/events.json": json.dumps(
        {
            "items": [
                {
                    "metadata": {"namespace": "ns-000", "uid": "event-1"},
                    "involvedObject": {
                        "kind": "Pod",
                        "name": "app-00000",
                        "uid": "uid-0",
                    },
                    "type": "Warning",
                    "reason": "BackOff",
                    "message": "synthetic retry",
                    "lastTimestamp": "2026-01-01T00:00:00Z",
                }
            ]
        }
    ),
    "rke2/podlogs/ns-000_app-00000_uid-0/web/0.log": "old instance\n",
    "rke2/podlogs/ns-000_app-00000_uid-0/web/1.log": "<script>window.pwned=1</script>\n"
    + "".join(f"line {i} 中文\n" for i in range(600))
    + "ONLY-AT-END\n",
    "rke2/podlogs/ns-000_app-00000_uid-0/init/0.log": "init complete\n",
    "journald/kubelet": "synthetic kubelet component log\n",
}
with tarfile.open(args.output, "w:gz") as archive:
    for name, value in files.items():
        raw = value.encode()
        info = tarfile.TarInfo("fixture/" + name)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
print(args.output)
