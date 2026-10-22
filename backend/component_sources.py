"""Identify concrete service sources separately from broad system/Pod scope."""

import re
from pathlib import PurePosixPath

GROUPS = {
    "kubernetes": "Kubernetes 核心",
    "distribution": "RKE2/K3s 服务",
    "runtime": "容器运行时",
    "host": "主机系统",
    "network": "网络与 DNS",
    "rancher": "Rancher 管理",
}
CORE = (
    "kube-apiserver",
    "kube-controller-manager",
    "kube-scheduler",
    "cloud-controller-manager",
    "etcd",
    "kubelet",
    "kube-proxy",
)
NETWORK = (
    "calico-node",
    "calico-kube-controllers",
    "cilium",
    "cilium-operator",
    "kube-flannel",
    "canal",
    "rke2-canal",
    "rke2-calico",
    "rke2-cilium",
    "coredns",
    "rke2-coredns",
)
RANCHER = (
    "rancher",
    "cattle-cluster-agent",
    "cattle-node-agent",
    "rancher-system-agent",
    "rancher-webhook",
)


def prefix(name, label):
    return name == label or name.startswith(label + "-")


def identify(path, namespace="", pod="", container=""):
    p = PurePosixPath(path.lower())
    parts = p.parts
    result = {
        "componentGroup": "",
        "serviceComponent": "",
        "sourceType": "pod" if pod else "file",
        "componentReason": "未匹配明确组件来源",
    }

    def found(group, component, source, reason):
        return {
            "componentGroup": group,
            "serviceComponent": component,
            "sourceType": source,
            "componentReason": reason,
        }

    # Pod identity must match a name boundary and trusted namespace, never a substring.
    if "/podlogs/" in path:
        if not pod:
            return result
        if namespace == "kube-system":
            for component in CORE:
                if prefix(pod, component) or (
                    container == component and pod.startswith(component + "-")
                ):
                    return found(
                        "kubernetes",
                        component,
                        "pod",
                        "kube-system 中的核心组件 Pod 名称",
                    )
        if namespace in (
            "kube-system",
            "calico-system",
            "cilium-system",
            "tigera-operator",
        ):
            for component in sorted(NETWORK, key=len, reverse=True):
                if prefix(pod, component):
                    return found(
                        "network", component, "pod", "网络/DNS 命名空间及组件 Pod 名称"
                    )
        if namespace == "cattle-system":
            for component in sorted(RANCHER, key=len, reverse=True):
                if prefix(pod, component):
                    return found(
                        "rancher",
                        component,
                        "pod",
                        "cattle-system 中的 Rancher 组件 Pod 名称",
                    )
        return result
    if not parts:
        return result
    service = p.name.lower()
    # Drop only known rotation suffixes, retaining complete component names.
    service = re.sub(r"(?:\.log)?(?:\.\d+)?(?:\.gz)?$", "", service)
    journal = parts[0] == "journald"
    source = "journald" if journal else "file"
    if (
        journal
        or any(x in parts for x in ("agent-logs", "server-logs", "containerlogs"))
        or parts[0] in ("rke2", "k3s", "rke", "rancher")
    ):
        if service in CORE:
            return found(
                "kubernetes", service, source, "明确的核心组件服务或日志文件名"
            )
        if service in (
            "rke2-server",
            "rke2-agent",
            "k3s",
            "k3s-server",
            "k3s-agent",
            "rke2",
        ):
            return found("distribution", service, source, "RKE2/K3s 服务日志")
        if service in ("containerd", "docker", "dockerd"):
            return found(
                "runtime",
                "docker" if service == "dockerd" else service,
                source,
                "容器运行时服务日志",
            )
        if service in RANCHER:
            return found("rancher", service, source, "Rancher 管理服务日志")
    if parts[0] == "systemlogs" or journal:
        if "sysstat-data" in parts:
            return found(
                "host", "sysstat", source, "主机 sysstat 采集文件（包含二进制数据）"
            )
        return found("host", service or p.name, source, "主机系统日志目录")
    return result
