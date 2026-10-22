#!/usr/bin/env python3
"""Generate synthetic display/certificate regression data without collected secrets."""

import io
import json
import tarfile
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)


def cert(days, ca=False):
    before, after = now - timedelta(days=365), now + timedelta(days=days)
    return f"""Certificate:
    Data:
        Issuer: CN = synthetic-ca
        Validity
            Not Before: {before.strftime('%b %d %H:%M:%S %Y GMT')}
            Not After : {after.strftime('%b %d %H:%M:%S %Y GMT')}
        Subject: CN = synthetic-service
        X509v3 extensions:
            X509v3 Basic Constraints:
                CA:{'TRUE' if ca else 'FALSE'}
            X509v3 Extended Key Usage:
                TLS Web Server Authentication
            X509v3 Subject Alternative Name:
                DNS:example.test
"""


pods = []
for name, ns, phase, ready, waiting in [
    ("app-running", "business", "Running", True, ""),
    ("app-notready", "business", "Running", False, ""),
    ("app-failed", "business", "Pending", False, "ImagePullBackOff"),
    ("app-completed", "business", "Succeeded", False, ""),
    ("app-pending", "business", "Pending", False, ""),
    ("app-unknown", "business", "Unknown", False, ""),
    ("kube-scheduler-fixture-node", "kube-system", "Running", True, ""),
    (
        "pushprox-kube-scheduler-proxy-x",
        "cattle-monitoring-system",
        "Running",
        True,
        "",
    ),
]:
    pods.append(
        {
            "metadata": {"name": name, "namespace": ns, "uid": name},
            "spec": {
                "nodeName": "fixture-node",
                "containers": [{"name": "main", "image": "example/image:1"}],
            },
            "status": {
                "phase": phase,
                "containerStatuses": [
                    {
                        "name": "main",
                        "ready": ready,
                        "restartCount": 9 if ready else 0,
                        "state": {"waiting": {"reason": waiting}} if waiting else {},
                    }
                ],
            },
        }
    )
files = {
    "summary.txt": "Hostname: fixture-node\nDistro: rke2\nGenerated: Wed Oct 21 16:21:06 CST 2026\n",
    "collector-output.log": "ok",
    "rke2/kubectl/pods.json": json.dumps({"items": pods}),
    "rke2/kubectl/nodes.json": json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "fixture-node"},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                }
            ]
        }
    ),
    "rke2/podlogs/business-app-running": "synthetic app log\n",
    "rke2/podlogs/business-app-running-previous": "previous synthetic log\n",
    "rke2/podlogs/kube-system-kube-scheduler-fixture-node": "synthetic scheduler log\n",
    "rke2/podlogs/cattle-monitoring-system-pushprox-kube-scheduler-proxy-x": "synthetic monitoring log\n",
    "rke2/agent-logs/kubelet.log": "synthetic kubelet log\n",
    "rke2/containerd.log": "synthetic runtime log\n",
    "journald/rke2-server": "synthetic rke2 service log\n",
    "journald/rke2-agent": "-- No entries --\n",
    "systemlogs/syslog": "synthetic syslog\n",
    "systemlogs/sysstat-data/sa21": "\0binary",
    "rke2/certs/server/expired.crt": cert(-1),
    "rke2/certs/server/expiring.crt": cert(30),
    "rke2/certs/server/valid.crt": cert(365),
    "rke2/certs/server/ca.crt": cert(3650, ca=True),
    "rke2/certs/server/invalid.crt": "invalid certificate",
}
with tarfile.open("/tmp/rancher-display-fixture.tar.gz", "w:gz") as archive:
    for name, text in files.items():
        raw = text.encode()
        info = tarfile.TarInfo("fixture-node/" + name)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
print("/tmp/rancher-display-fixture.tar.gz")
