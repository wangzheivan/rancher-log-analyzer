import json
import pytest
from backend.catalog import IndexedBundle
from backend.component_sources import identify


@pytest.mark.parametrize(
    "path,namespace,pod,group,component",
    [
        (
            "rke2/podlogs/kube-system-kube-apiserver-node",
            "kube-system",
            "kube-apiserver-node",
            "kubernetes",
            "kube-apiserver",
        ),
        (
            "rke2/podlogs/kube-system-kube-scheduler-node",
            "kube-system",
            "kube-scheduler-node",
            "kubernetes",
            "kube-scheduler",
        ),
        (
            "rke2/podlogs/kube-system-cloud-controller-manager-node",
            "kube-system",
            "cloud-controller-manager-node",
            "kubernetes",
            "cloud-controller-manager",
        ),
        ("rke2/agent-logs/kubelet.log", "", "", "kubernetes", "kubelet"),
        ("journald/rke2-server", "", "", "distribution", "rke2-server"),
        ("journald/k3s", "", "", "distribution", "k3s"),
        ("rke2/containerd.log", "", "", "runtime", "containerd"),
        ("systemlogs/syslog.1", "", "", "host", "syslog"),
        ("systemlogs/sysstat-data/sa21", "", "", "host", "sysstat"),
        ("journald/rancher-system-agent", "", "", "rancher", "rancher-system-agent"),
        (
            "rke2/podlogs/calico-system-calico-node-x",
            "calico-system",
            "calico-node-x",
            "network",
            "calico-node",
        ),
        (
            "rke2/podlogs/kube-system-rke2-coredns-x",
            "kube-system",
            "rke2-coredns-x",
            "network",
            "rke2-coredns",
        ),
    ],
)
def test_service_sources(path, namespace, pod, group, component):
    found = identify(path, namespace, pod)
    assert (found["componentGroup"], found["serviceComponent"]) == (group, component)


@pytest.mark.parametrize(
    "namespace,pod",
    [
        ("cattle-monitoring-system", "pushprox-kube-scheduler-proxy-x"),
        ("kube-system", "pushprox-kube-apiserver-x"),
        ("business", "kube-apiserver-fake"),
        ("kube-system", "kube-schedulerfake"),
        ("cattle-neuvector-system", "neuvector-controller-x"),
        ("cattle-fleet-system", "fleet-agent-x"),
        ("kube-system", "helm-install-rke2-coredns-x"),
    ],
)
def test_no_substring_or_namespace_only_matches(namespace, pod):
    assert (
        identify("rke2/podlogs/" + namespace + "-" + pod, namespace, pod)[
            "componentGroup"
        ]
        == ""
    )


def test_catalog_groups_node_candidates_and_valid_empty(tmp_path):
    root = tmp_path / "files"
    files = {
        "summary.txt": "Hostname: node1\nDistro: rke2\n",
        "journald/rke2-agent": "-- No entries --\n",
        "rke2/agent-logs/kubelet.log": "kubelet",
        "rke2/containerd.log": "containerd",
        "systemlogs/syslog": "syslog",
        "systemlogs/sysstat-data/sa21": "\0binary",
        "rke2/kubectl/pods.json": json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "kube-scheduler-node2",
                            "namespace": "kube-system",
                        },
                        "spec": {"nodeName": "node2"},
                    },
                    {
                        "metadata": {
                            "name": "pushprox-kube-scheduler-proxy-x",
                            "namespace": "cattle-monitoring-system",
                        },
                        "spec": {"nodeName": "node2"},
                    },
                ]
            }
        ),
        "rke2/podlogs/kube-system-kube-scheduler-node2": "scheduler",
        "rke2/podlogs/cattle-monitoring-system-pushprox-kube-scheduler-proxy-x": "monitoring",
    }
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    assert b.catalog("logs")["total"] == 7
    assert b.catalog("componentLogs")["total"] == 6
    assert b.catalog("componentLogs", component_group="kubernetes")["total"] == 2
    assert b.catalog("componentLogs", node="node2")["total"] == 1
    assert b.catalog("components", node="node2")["items"][0]["name"] == "kube-scheduler"
    assert b.catalog("components", component_group="runtime")["total"] == 1
    empty = b.catalog("componentLogs", component="rke2-agent")["items"][0]
    assert empty["status"] == "empty" and empty["note"] == "有效无记录"
    sysstat = next(
        l for l in b.catalog("componentLogs")["items"] if "sa21" in l["path"]
    )
    assert sysstat["status"] == "unsupported"
    cursor = b.catalog("logs", limit=1)["nextCursor"]
    with pytest.raises(ValueError, match="游标"):
        b.catalog("componentLogs", limit=1, cursor=cursor)
    with pytest.raises(ValueError, match="分组"):
        b.catalog("componentLogs", component_group="invalid")


def test_specific_component_names_take_precedence():
    assert (
        identify(
            "rke2/podlogs/cattle-system-rancher-webhook-x",
            "cattle-system",
            "rancher-webhook-x",
        )["serviceComponent"]
        == "rancher-webhook"
    )
    assert (
        identify(
            "rke2/podlogs/kube-system-cilium-operator-x",
            "kube-system",
            "cilium-operator-x",
        )["serviceComponent"]
        == "cilium-operator"
    )
