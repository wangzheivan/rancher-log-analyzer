import json
import math

VERSION = "screening-1"
DEFAULT_THRESHOLDS = {
    "cpu": [85, 95],
    "iowait": [10, 25],
    "load": [1, 2],
    "memoryAvailable": [15, 5],
    "disk": [85, 95],
    "inode": [85, 95],
    "fileHandles": [85, 95],
    "etcdQuota": [80, 95],
}
CATEGORIES = {
    "cluster": "集群与 Pod",
    "services": "节点服务",
    "initialization": "初始化与内核",
    "resources": "主机资源",
    "etcd": "etcd",
    "certificates": "证书",
    "system": "系统与运行时",
}
DOCS = {
    "cluster": "https://kubernetes.io/docs/reference/node/node-status/",
    "services": "https://docs.rke2.io/architecture",
    "initialization": "https://docs.rke2.io/known_issues",
    "swap": "https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/",
    "runtime": "https://kubernetes.io/docs/setup/production-environment/container-runtimes/",
    "etcd": "https://etcd.io/docs/v3.5/faq/#what-does-the-etcd-warning-apply-entries-took-too-long-mean",
    "metrics": "https://etcd.io/docs/v3.5/metrics/",
}


def thresholds(raw):
    supplied = json.loads(raw or "{}")
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULT_THRESHOLDS):
        raise ValueError("ANALYSIS_THRESHOLDS 只允许内置阈值名称")
    result = {**DEFAULT_THRESHOLDS, **supplied}
    for name, pair in result.items():
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v < 0
                for v in pair
            )
        ):
            raise ValueError("分析阈值必须是两个非负有限数字")
        if name != "load" and any(v > 100 for v in pair):
            raise ValueError("百分比阈值不能超过100")
        if (pair[0] <= pair[1]) == (name == "memoryAvailable"):
            raise ValueError("分析阈值的关注/高风险顺序错误")
    return result
