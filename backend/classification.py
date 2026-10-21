"""Deterministic display categories; no health diagnosis."""

import json

SYSTEM_NAMESPACES = {
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "calico-system",
    "tigera-operator",
    "longhorn-system",
    "ingress-nginx",
    "fleet-system",
    "fleet-default",
    "istio-system",
    "suse-observability",
}
COMPONENTS = (
    "kube-apiserver",
    "kube-controller-manager",
    "kube-scheduler",
    "kube-proxy",
    "kubelet",
    "etcd",
    "containerd",
    "docker",
    "rancher-system-agent",
    "cattle-cluster-agent",
    "rancher-webhook",
    "fleet-agent",
    "rke2-server",
    "rke2-agent",
    "k3s",
    "calico",
    "coredns",
    "metrics-server",
    "traefik",
)


def load_rules(raw):
    rules = json.loads(raw or "[]")
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("LOG_CLASSIFICATION_RULES 必须是最多 100 项的 JSON 数组")
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("scope") not in (
            "system",
            "business",
            "unknown",
        ):
            raise ValueError("分类规则 scope 必须为 system/business/unknown")
        if not any(
            rule.get(key) for key in ("namespace", "podPrefix", "componentPrefix")
        ):
            raise ValueError("分类规则至少指定 namespace、podPrefix 或 componentPrefix")
        if any(
            key not in ("namespace", "podPrefix", "componentPrefix", "scope")
            for key in rule
        ):
            raise ValueError("分类规则包含未知字段")
        if any(
            not isinstance(value, str) or len(value) > 253 for value in rule.values()
        ):
            raise ValueError("分类规则字段必须为不超过 253 字符的字符串")
    return rules


def classify(namespace="", pod="", source="", rules=()):
    lowered = (pod + "/" + source).lower()
    component = next((c for c in COMPONENTS if c in lowered), "")
    for rule in rules:
        if rule.get("namespace") and namespace != rule["namespace"]:
            continue
        if rule.get("podPrefix") and not pod.startswith(rule["podPrefix"]):
            continue
        if rule.get("componentPrefix") and not component.startswith(
            rule["componentPrefix"]
        ):
            continue
        return rule["scope"], component or "其他组件", "显式配置规则"
    if (
        component
        or namespace in SYSTEM_NAMESPACES
        or namespace.startswith(("cattle-", "rke2-", "kube-"))
    ):
        return (
            "system",
            component or ("平台 Pod" if namespace else "系统日志"),
            "内置组件/命名空间规则",
        )
    if (
        source.startswith(("journald/", "systemlogs/"))
        or "/agent-logs/" in source
        or "/server-logs/" in source
        or "/containerlogs/" in source
    ):
        return "system", component or source.split("/")[0], "系统服务日志目录"
    if namespace and pod:
        return "business", "", "非系统命名空间中的 Pod"
    return "unknown", "", "缺少足够的分类信息"
