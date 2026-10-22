"""Versioned deterministic checks. Missing evidence is not a pass."""

import json
import re
from . import parsers as p
from .config import DOCS
from ..catalog import identity
from ..component_sources import identify
from ..certificates import certificate_page


def resource_obj(row, kind):
    return {
        k: row.get(k, "") for k in ("id", "name", "namespace", "node", "uid", "source")
    } | {
        "kind": kind,
        "entityId": row["id"],
        "node": row["name"] if kind == "Node" else row.get("node", ""),
    }


def structured(e):
    e.host = {
        "kind": "Node",
        "id": "collected-host",
        "name": e.bundle.header["hostname"],
        "node": e.bundle.header["hostname"],
    }
    with e.bundle.connection() as conn:
        sources = {
            r["name"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM sources WHERE name IN ('pods','nodes','events')"
            )
        }
    for kind in ("pods", "nodes", "events"):
        source = sources.get(kind)
        if not source or source["state"] in ("failed", "unknown"):
            e.check(
                "source." + kind,
                {"kind": "File", "id": "source-" + kind, "name": kind},
                "unknown",
                "cluster",
                kind + "清单未提供可完整解析的数据；局部Describe不能证明全局覆盖",
                source["source"] if source else "",
            )
    found = []
    node_count = pod_count = 0
    for row in e.objects("nodes"):
        if row is None:
            yield
            continue
        node_count += 1
        obj = resource_obj(row, "Node")
        if row["name"] == e.host["name"]:
            found.append(obj)
        if row.get("ready") == "False":
            e.emit(
                "node.ready",
                obj,
                "cluster",
                "high",
                "snapshot",
                "Node 未就绪",
                "Ready=False",
                "核对节点心跳、kubelet、运行时和关联事件。",
                source=row.get("source", ""),
                docs=DOCS["cluster"],
            )
        elif row.get("ready") == "True":
            e.check("node.ready", obj, "passed", "cluster")
        else:
            e.check(
                "node.ready",
                obj,
                "unknown",
                "cluster",
                "Node Ready 状态未知",
                row.get("source", ""),
            )
        conditions = {c["type"]: c for c in row.get("conditions", [])}
        if len(conditions) < 5:
            description = e.bundle.entity("nodes", row["id"]).get("describe")
            if description and not description.get("truncated"):
                for line in description["sections"].get("Conditions", "").splitlines():
                    match = re.match(
                        r"\s*(Ready|MemoryPressure|DiskPressure|PIDPressure|NetworkUnavailable)\s+(True|False|Unknown)\b(.*)",
                        line,
                    )
                    if match and match[1] not in conditions:
                        conditions[match[1]] = {
                            "type": match[1],
                            "status": match[2],
                            "message": match[3].strip(),
                            "source": description["source"],
                        }

        for name in (
            "MemoryPressure",
            "DiskPressure",
            "PIDPressure",
            "NetworkUnavailable",
        ):
            condition = conditions.get(name)
            if condition and condition.get("status") == "True":
                e.emit(
                    "node." + name,
                    obj,
                    "cluster",
                    "high",
                    "snapshot",
                    "Node " + name,
                    condition.get("reason", "") + " " + condition.get("message", ""),
                    "核查节点对应资源或网络状态及关联事件。",
                    source=condition.get("source", row.get("source", "")),
                    docs=DOCS["cluster"],
                )
            elif condition and condition.get("status") == "False":
                e.check("node." + name, obj, "passed", "cluster")
            else:
                e.check(
                    "node." + name,
                    obj,
                    "unknown",
                    "cluster",
                    name + " 未提供明确状态",
                    row.get("source", ""),
                )
    if not node_count:
        e.check(
            "cluster.nodes",
            e.host,
            "unknown",
            "cluster",
            "节点清单缺失、为空或无法解析，无法判断节点状态",
        )
    if len(found) == 1:
        e.host = found[0]
    else:
        e.host["name"] += "（未唯一匹配集群 Node）"
        e.check(
            "host.identity",
            e.host,
            "unknown",
            "cluster",
            "采集主机名称未唯一匹配集群 Node；主机指标不分配给其他节点",
        )
    for row in e.objects("pods", detail=True):
        if row is None:
            yield
            continue
        pod_count += 1
        obj = resource_obj(row, "Pod")
        state = row.get("status", "Unknown")
        if state in ("Completed", "Succeeded"):
            e.check("pod.state", obj, "passed", "cluster")
            continue
        core = (
            identify("x/podlogs/" + row["name"], row.get("namespace", ""), row["name"])[
                "componentGroup"
            ]
            == "kubernetes"
        )
        detail = row.get("_detail") or {}
        statuses = detail.get("status", {}).get("containerStatuses", []) + detail.get(
            "status", {}
        ).get("initContainerStatuses", [])
        current_oom = any(
            s.get("state", {}).get("terminated", {}).get("reason") == "OOMKilled"
            for s in statuses
        )
        prior_oom = any(
            s.get("lastState", {}).get("terminated", {}).get("reason") == "OOMKilled"
            for s in statuses
        )
        if state == "Running" and not row.get("attention") and not current_oom:
            e.check("pod.state", obj, "passed", "cluster")
        elif state in ("Unknown", ""):
            e.check(
                "pod.state",
                obj,
                "unknown",
                "cluster",
                "Pod 状态未知",
                row.get("source", ""),
            )
        else:
            ordinary = state in (
                "Pending",
                "Terminating",
                "ContainerCreating",
                "PodInitializing",
            ) or bool(re.fullmatch(r"Init:\d+/\d+", state))
            warning = False
            if ordinary:
                # Filter by indexed namespace/name and precise UID association.
                with e.bundle.connection() as conn:
                    warning = (
                        conn.execute(
                            "SELECT 1 FROM items WHERE kind='events' AND ns=? AND json_extract(payload,'$.objectName')=? AND lower(json_extract(payload,'$.objectKind'))='pod' AND json_extract(payload,'$.type')='Warning' AND (coalesce(json_extract(payload,'$.objectUid'),'')='' OR json_extract(payload,'$.objectUid')=?) LIMIT 1",
                            (row.get("namespace", ""), row["name"], row.get("uid", "")),
                        ).fetchone()
                        is not None
                    )
            severity = (
                "high"
                if core and not ordinary
                else "warning" if warning or not ordinary else "info"
            )
            e.emit(
                "pod.state",
                obj,
                "cluster",
                severity,
                "snapshot",
                "Pod 状态需核查",
                f'{state}；就绪 {row.get("ready","未知")}；历史重启 {row.get("restartCount",0)}',
                "优先查看关联事件和当前容器状态，再核对该实例的日志；重启次数不直接代表当前故障。",
                source=row.get("source", ""),
                docs=DOCS["cluster"],
            )
        if current_oom or prior_oom:
            e.emit(
                "pod.oom",
                obj,
                "cluster",
                "high" if core and current_oom else "warning",
                "snapshot" if current_oom else "history",
                "容器 OOMKilled" if current_oom else "容器上一次状态为 OOMKilled",
                (
                    "当前终止状态 OOMKilled"
                    if current_oom
                    else "lastState.terminated.reason=OOMKilled"
                ),
                "核对内存限制、节点内存和对应时间的内核日志；上次终止不代表当前故障。",
                source=row.get("source", ""),
            )
    if not pod_count:
        e.check(
            "cluster.pods",
            e.host,
            "unknown",
            "cluster",
            "Pod清单缺失、为空或无法解析，无法判断工作负载状态",
        )
    yield
    host_checks(e)
    yield
    etcd_checks(e)
    yield
    cursor = ""
    while True:
        result = certificate_page(e.bundle, limit=50, cursor=cursor)
        for cert in result["items"]:
            obj = {
                "kind": "Certificate",
                "id": cert["id"],
                "name": cert["name"],
                "node": cert["node"],
                "source": cert["source"],
            }
            validity = cert["validity"]
            if validity == "unknown":
                e.check(
                    "cert.validity",
                    obj,
                    "unknown",
                    "certificates",
                    cert.get("note", "证书无法判断"),
                    cert["source"],
                )
            elif validity in ("expired", "notYetValid", "expiring"):
                e.emit(
                    "cert.validity",
                    obj,
                    "certificates",
                    "high" if validity == "expired" else "warning",
                    "snapshot",
                    "采集证书副本的有效期需关注",
                    f'按分析时刻 {result["referenceTime"]} 检查：{validity}；到期 {cert.get("notAfter")}；文件内第 {cert["sourceIndex"]} 份',
                    "在证书页核对用途与时间。此结论仅针对采集副本，不证明在线集群仍使用该证书。",
                    source=cert["source"],
                )
            else:
                e.check("cert.validity", obj, "passed", "certificates")
        cursor = result["nextCursor"]
        if not cursor:
            break
        yield
    if not result["total"]:
        e.check(
            "cert.available",
            e.host,
            "unknown",
            "certificates",
            "未发现可检查的证书信息",
        )


def host_checks(e):
    obj = e.host
    unit_text = e.read("systeminfo/systemd-units")
    units = p.units(unit_text)
    server = units.get("rke2-server.service") or units.get("k3s.service")
    agent = units.get("rke2-agent.service") or units.get("k3s-agent.service")
    # A loaded server unit is evidence of server role, not its enabled flag or journal presence.
    if server and server["active"] == "active":
        role, service = "server", (
            "rke2-server.service" if "rke2-server.service" in units else "k3s.service"
        )
    elif agent and agent["active"] == "active":
        role, service = "agent", (
            "rke2-agent.service"
            if "rke2-agent.service" in units
            else "k3s-agent.service"
        )
    elif (
        server
        and server["load"] == "loaded"
        and (not agent or agent["load"] != "loaded")
    ):
        role, service = "server", (
            "rke2-server.service" if "rke2-server.service" in units else "k3s.service"
        )
    elif (
        agent
        and agent["load"] == "loaded"
        and (not server or server["load"] != "loaded")
    ):
        role, service = "agent", (
            "rke2-agent.service"
            if "rke2-agent.service" in units
            else "k3s-agent.service"
        )
    else:
        role, service = "unknown", ""
    e.role = role
    e.fact(
        "host.role",
        "采集节点角色",
        role,
        "systeminfo/systemd-units",
        "按采集服务状态识别；server无需独立agent同时运行",
    )
    if service:
        status = units[service]
        e.fact(
            "service.distribution",
            service,
            status["active"] + " / " + status["sub"],
            "systeminfo/systemd-units",
            "服务状态不代替集群整体健康",
        )
        if status["active"] == "active" and status["sub"] == "running":
            e.check("service.distribution", obj, "passed", "services")
        else:
            e.emit(
                "service.distribution",
                obj,
                "services",
                "high",
                "snapshot",
                "节点必需服务未运行",
                service + ": " + json.dumps(status),
                "核对服务退出原因和对应journald；server不要求独立agent同时运行。",
                source="systeminfo/systemd-units",
                docs=DOCS["services"],
            )
    else:
        e.check(
            "service.distribution",
            obj,
            "unknown",
            "services",
            "未取得可确认角色的 RKE2/K3s 服务状态",
            "systeminfo/systemd-units",
        )
    runtime = units.get("containerd.service") or units.get("docker.service")
    if runtime and runtime["load"] == "loaded":
        if runtime["active"] == "failed":
            e.emit(
                "service.runtime",
                obj,
                "services",
                "warning" if e.bundle.distro in ("rke2", "k3s") else "high",
                "snapshot",
                "运行时 systemd 服务失败",
                str(runtime),
                "核对该服务是否为集群实际使用的运行时；RKE2也可管理内嵌containerd。",
                source="systeminfo/systemd-units",
                docs=DOCS["runtime"],
            )
        elif runtime["active"] == "active":
            e.check("service.runtime", obj, "passed", "services")
        else:
            e.check(
                "service.runtime",
                obj,
                "unknown",
                "services",
                "独立运行时服务未运行，需确认集群是否使用内嵌运行时",
                "systeminfo/systemd-units",
            )
    else:
        e.check(
            "service.runtime",
            obj,
            "unknown",
            "services",
            "未提供独立运行时服务状态；不据此推断内嵌运行时故障",
        )
    for unit in ("nm-cloud-setup.service", "nm-cloud-setup.timer"):
        if units.get(unit, {}).get("active") == "active" and e.bundle.distro == "rke2":
            e.emit(
                "network." + unit,
                obj,
                "initialization",
                "warning",
                "snapshot",
                "网络管理服务可能与 CNI 冲突",
                unit + " active",
                "结合操作系统和CNI核对RKE2已知问题，不自动修改服务。",
                source="systeminfo/systemd-units",
                docs=DOCS["initialization"],
            )
    for unit in ("NetworkManager.service", "firewalld.service"):
        if units.get(unit, {}).get("active") == "active":
            e.emit(
                "network." + unit,
                obj,
                "initialization",
                "info",
                "snapshot",
                "网络服务适用性需人工核对",
                unit + " active",
                "检查CNI类型、接口忽略规则及防火墙规则；仅开启服务不足以证明冲突。",
                source="systeminfo/systemd-units",
                docs=DOCS["initialization"],
            )
    e.check(
        "clock.synchronization",
        obj,
        "unknown",
        "initialization",
        "时间同步服务运行不等于已同步；缺少偏移/同步状态证据",
    )
    sysctl = p.sysctls(e.read("systeminfo/sysctla"))
    forward = sysctl.get("net.ipv4.ip_forward", "").strip()
    if forward == "1":
        e.check("init.ipv4Forward", obj, "passed", "initialization")
    elif forward == "0":
        e.emit(
            "init.ipv4Forward",
            obj,
            "initialization",
            "warning",
            "snapshot",
            "IPv4 转发未开启",
            "net.ipv4.ip_forward=0",
            "确认集群是否使用IPv4及对应CNI的转发要求；不适用于仅IPv6场景。",
            source="systeminfo/sysctla",
            docs=DOCS["runtime"],
        )
    else:
        e.check(
            "init.ipv4Forward",
            obj,
            "unknown",
            "initialization",
            "缺少明确 IPv4 转发状态",
            "systeminfo/sysctla",
        )
    e.check(
        "init.bridge",
        obj,
        "unknown",
        "initialization",
        "桥接参数需结合CNI及其具体网络模式确认；不套用统一桥接基线",
        "systeminfo/sysctla",
    )
    kube_config = ""
    runtime_config = ""
    kube_source = ""
    runtime_source = ""
    for path in (
        "rke2/kubelet-config.yaml",
        "k3s/kubelet-config.yaml",
        "kubelet-config.yaml",
        "rke2/agent/etc/kubelet.conf",
    ):
        text = e.read(path, 65536)
        if re.search(r'cgroupDriver["\s:]+(?:systemd|cgroupfs)', text):
            kube_config = text
            kube_source = path
            break
    for path in (
        "rke2/containerd/config.toml",
        "rke2/containerd-config.toml",
        "rke2/agent/etc/containerd/config.toml",
        "containerd/config.toml",
    ):
        text = e.read(path, 65536)
        if re.search(r"SystemdCgroup\s*=\s*(?:true|false)", text):
            runtime_config = text
            runtime_source = path
            break
    kd = re.search(r'cgroupDriver["\s:]+(systemd|cgroupfs)', kube_config)
    rd = re.search(r"SystemdCgroup\s*=\s*(true|false)", runtime_config)
    if (
        kd
        and rd
        and kube_source not in e.truncated
        and runtime_source not in e.truncated
    ):
        runtime_driver = "systemd" if rd[1] == "true" else "cgroupfs"
        if kd[1] != runtime_driver:
            e.emit(
                "init.cgroup",
                obj,
                "initialization",
                "warning",
                "snapshot",
                "采集配置中的 cgroup 驱动不一致",
                f"kubelet={kd[1]}, runtime={runtime_driver}；runtime来源 {runtime_source}",
                "核对配置文件是否为实际生效配置及版本的驱动自动探测行为；不要直接修改已加入集群节点的驱动。",
                source=kube_source,
                docs=DOCS["runtime"],
            )
        else:
            e.emit(
                "init.cgroup",
                obj,
                "initialization",
                "info",
                "snapshot",
                "采集配置中的 cgroup 驱动一致",
                f"kubelet/runtime={kd[1]}；runtime来源 {runtime_source}",
                "配置文件一致不证明已经生效；结合进程参数和对应版本的自动探测行为核查。",
                source=kube_source,
                docs=DOCS["runtime"],
            )
    else:
        e.check(
            "init.cgroup",
            obj,
            "unknown",
            "initialization",
            "未采集可相互验证的 kubelet/runtime 有效配置，无法判断 cgroup 驱动一致性",
        )
    e.check(
        "init.persistent",
        obj,
        "unknown",
        "initialization",
        "sysctl与swap快照不证明重启后的持久配置",
    )
    for key in (
        "fs.inotify.max_user_instances",
        "fs.inotify.max_user_watches",
        "vm.swappiness",
        "vm.overcommit_memory",
        "vm.panic_on_oom",
        "kernel.panic",
        "kernel.panic_on_oops",
        "fs.file-max",
        "net.bridge.bridge-nf-call-iptables",
        "net.bridge.bridge-nf-call-ip6tables",
    ):
        if key in sysctl:
            e.emit(
                "init.value." + key,
                obj,
                "initialization",
                "info",
                "snapshot",
                "关键配置快照：" + key,
                key + "=" + sysctl[key],
                "此为配置展示，是否需要调整取决于版本、CNI及业务负载，不作为通用故障。",
                source="systeminfo/sysctla",
                docs=DOCS["runtime"],
            )
    mem = p.memory(e.read("systeminfo/freeh"))
    if mem.get("swapTotal") is not None:
        e.writer.execute(
            "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)",
            (
                identity("swap", e.object_key(obj)),
                "host.swapTotal",
                "Swap总量（字节）",
                mem["swapTotal"],
                "systeminfo/freeh",
                "0表示当前快照没有启用swap，不证明重启后配置",
            ),
        )
    if mem.get("swapTotal") == 0:
        e.check("init.swap", obj, "passed", "initialization")
    elif mem.get("swapTotal") is not None:
        e.emit(
            "init.swap",
            obj,
            "initialization",
            "warning",
            "snapshot",
            "当前节点启用了 swap",
            f'Swap total={mem["swapTotal"]}, used={mem.get("swapUsed")}',
            "结合 Kubernetes 版本、failSwapOn及memorySwap配置核对；不能只凭swap开启判定故障。",
            source="systeminfo/freeh",
            docs=DOCS["swap"],
        )
    else:
        e.check(
            "init.swap",
            obj,
            "unknown",
            "initialization",
            "未提供可解析的swap状态",
            "systeminfo/freeh",
        )
    if mem.get("total") and mem.get("available") is not None:
        e.metric(
            "host.memoryAvailable",
            obj,
            "可用内存占比(%)",
            100 * mem["available"] / mem["total"],
            source="systeminfo/freeh",
            invert=True,
        )
    else:
        e.metric(
            "host.memoryAvailable",
            obj,
            "可用内存占比(%)",
            None,
            source="systeminfo/freeh",
            invert=True,
        )
    cpu = p.cpu(e.read("systeminfo/vmstat"), e.read("systeminfo/top"))
    for key, label in [
        ("cpu", "CPU非空闲占比(%，含I/O wait/steal)"),
        ("iowait", "I/O wait(%)"),
    ]:
        e.metric(
            "host." + key,
            obj,
            label,
            cpu["busy" if key == "cpu" else key] if cpu else None,
            source=cpu["source"] if cpu else "systeminfo/vmstat",
            note=cpu["note"] if cpu else "",
        )
    cpus = re.search(r"(?m)^CPU\(s\):\s*(\d+)", e.read("systeminfo/lscpu"))
    if not cpus:
        cpu_count = len(re.findall(r"(?m)^processor\s*:", e.read("systeminfo/cpuinfo")))
    else:
        cpu_count = int(cpus[1])
    load = re.search(
        r"load average[s]?:\s*(\d+(?:[.,]\d+)?)", e.read("systeminfo/uptime")
    )
    e.metric(
        "host.load",
        obj,
        "1分钟负载/逻辑CPU",
        p.number(load[1]) / cpu_count if load and cpu_count else None,
        source="systeminfo/uptime",
        note="负载包含等待I/O的任务，不等于CPU使用率",
    )
    for rule, source, label in [
        ("disk", "systeminfo/dfh", "磁盘容量占用(%)"),
        ("inode", "systeminfo/dfi", "inode占用(%)"),
    ]:
        disks = p.disks(e.read(source))
        if not disks:
            e.check(
                "host." + rule,
                obj,
                "unknown",
                "resources",
                "未取得可解析的实际文件系统数据",
                source,
            )
        for disk in disks:
            disk_obj = {
                **obj,
                "id": identity(
                    e.object_key(obj), rule, disk["filesystem"], disk["total"]
                ),
                "analysisObjectKey": identity(
                    e.object_key(obj), rule, disk["filesystem"], disk["total"]
                ),
            }
            e.metric(
                "host." + rule,
                disk_obj,
                label,
                disk["percent"],
                source=source,
                note=json.dumps(disk, ensure_ascii=False),
            )
    handles = e.read("systeminfo/file-nr").split()
    try:
        used, max_handles = max(0, int(handles[0]) - int(handles[1])), int(handles[2])
        percent = 100 * used / max_handles if max_handles > 0 else None
    except (ValueError, IndexError):
        percent = None
    e.metric(
        "host.fileHandles",
        obj,
        "系统文件句柄占用(%)",
        percent,
        source="systeminfo/file-nr",
        note="系统级file-nr；采集器shell的ulimit不代表目标服务限制",
    )
    processes = p.processes(e.read("systeminfo/ps"))
    if processes is None or "systeminfo/ps" in e.truncated:
        e.check(
            "host.zombies",
            obj,
            "unknown",
            "resources",
            "进程状态文件缺失、无法解析或未完整读取",
            "systeminfo/ps",
        )
    elif processes:
        e.writer.execute(
            "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)",
            (
                identity("zombies", e.object_key(obj)),
                "host.zombies",
                "僵尸进程数",
                len(processes),
                "systeminfo/ps",
                "按STAT判断，仅属于采集节点",
            ),
        )
        e.emit(
            "host.zombies",
            obj,
            "resources",
            "warning",
            "snapshot",
            "采集到僵尸进程",
            f"{len(processes)} 个；前10个PID/STAT：" + json.dumps(processes[:10]),
            "核查父进程是否及时回收；不要仅根据命令中的zombie关键字判断。",
            source="systeminfo/ps",
        )
    else:
        e.writer.execute(
            "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)",
            (
                identity("zombies", e.object_key(obj)),
                "host.zombies",
                "僵尸进程数",
                0,
                "systeminfo/ps",
                "按STAT判断，仅属于采集节点",
            ),
        )
        e.check("host.zombies", obj, "passed", "resources")


def etcd_checks(e):
    obj = {**e.host, "kind": "Etcd", "id": "local-etcd", "uid": ""}
    health = e.read("etcd/endpointhealth")
    status = e.read("etcd/endpointstatus")
    members = e.read("etcd/memberlist")
    if not health and not status and not members:
        e.check(
            "etcd.available",
            obj,
            "na" if e.role == "agent" else "unknown",
            "etcd",
            "未提供etcd检查数据，不能推断健康",
        )
        return
    metrics = {}
    metric_sets = []
    with e.bundle.connection() as conn:
        paths = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM items WHERE kind='files' AND instr(name,'etcd-metrics-')>0 ORDER BY name LIMIT 20"
            )
        ]
    # files.name is relative path in the catalog.
    for path in paths:
        values = p.metrics(e.read(path))
        metric_sets.append((path, values))
        if not metrics:
            metrics = values
    leader_values = [
        (path, values.get("etcd_server_has_leader")) for path, values in metric_sets
    ]
    metric_leader = (
        0
        if any(v == 0 for _, v in leader_values)
        else 1 if any(v == 1 for _, v in leader_values) else None
    )
    leader_source = next(
        (path for path, value in leader_values if value == 0),
        paths[0] if paths else "etcd/endpointstatus",
    )
    e.fact(
        "etcd.leader",
        "etcd leader 证据",
        (
            "has_leader=" + str(metric_leader)
            if metric_leader is not None
            else "需结合端点状态核对"
        ),
        leader_source,
        "仅代表采集到的成员；follower本身正常",
    )
    table = p.pipe_table(status)
    if metric_leader == 0:
        e.emit(
            "etcd.leader",
            obj,
            "etcd",
            "high",
            "snapshot",
            "采集成员没有 leader",
            "etcd_server_has_leader=0",
            "核查成员连通性、磁盘、选举与可用投票成员；只表示该采集成员的证据。",
            source=leader_source,
            docs=DOCS["metrics"],
        )
    elif metric_leader == 1 or any(
        r.get("IS LEADER", "").lower() == "true" for r in table
    ):
        e.check("etcd.leader", obj, "passed", "etcd")
    else:
        e.check(
            "etcd.leader",
            obj,
            "unknown",
            "etcd",
            "所采集端点未显示leader，可能仅采集到follower，不能据此判定无leader",
            "etcd/endpointstatus",
        )
    member_rows = [
        line.split(",") for line in members.splitlines() if len(line.split(",")) >= 5
    ]
    e.fact(
        "etcd.members",
        "etcd 成员启动标识",
        f'{sum(parts[1].strip()=="started" for parts in member_rows)} started / {len(member_rows)} 条记录',
        "etcd/memberlist",
        "started不是端点健康探测；单成员不自动判故障",
    )
    for parts in member_rows:
        member = {
            **obj,
            "id": parts[0].strip(),
            "name": parts[2].strip() or parts[0].strip(),
        }
        if parts[1].strip() != "started":
            e.emit(
                "etcd.member",
                member,
                "etcd",
                "warning",
                "snapshot",
                "etcd 成员未标为 started",
                parts[1].strip(),
                "结合该成员端点健康核查；成员启动标识本身不等于健康探测。",
                source="etcd/memberlist",
            )
    good = re.findall(r"(?m)^\s*(https?://\S+) is healthy:", health)
    bad = [
        line
        for line in health.splitlines()
        if re.search(
            r"unhealthy|failed|error|deadline exceeded|connection refused", line, re.I
        )
    ]
    e.fact(
        "etcd.health",
        "etcd 端点健康输出",
        f"{len(set(good))} 明确健康 / {len(bad)} 失败输出",
        "etcd/endpointhealth",
        "未采集的端点不推断正常",
    )
    if bad:
        e.emit(
            "etcd.health",
            obj,
            "etcd",
            "high",
            "snapshot",
            "etcd 端点健康探测失败",
            "\n".join(bad[:10]),
            "核查明确失败的端点，结合网络、证书和etcd进程检查。",
            source="etcd/endpointhealth",
        )
    elif good:
        e.check("etcd.health", obj, "passed", "etcd")
    else:
        e.check(
            "etcd.health",
            obj,
            "unknown",
            "etcd",
            "未取得明确的端点健康探测结果",
            "etcd/endpointhealth",
        )
    expected_urls = {parts[4].strip() for parts in member_rows if parts[4].strip()}
    if not member_rows or not expected_urls or not expected_urls.issubset(set(good)):
        e.check(
            "etcd.memberCoverage",
            obj,
            "unknown",
            "etcd",
            f"成员清单 {len(member_rows)} 个，明确健康端点 {len(set(good))} 个；缺少探测不等于成员失败",
            "etcd/memberlist",
        )
    else:
        e.check("etcd.memberCoverage", obj, "passed", "etcd")
    for row in table:
        if row.get("ERRORS"):
            e.emit(
                "etcd.endpointErrors",
                {**obj, "id": row.get("ID", obj["id"])},
                "etcd",
                "high",
                "snapshot",
                "etcd 端点报告错误",
                row["ERRORS"],
                "核对具体端点错误和日志。",
                source="etcd/endpointstatus",
            )
    alarm_path = e.bundle.root / "etcd/alarmlist"
    if alarm_path.is_file():
        alarms = e.read("etcd/alarmlist").strip()
        if alarms:
            if re.search(r"NOSPACE|CORRUPT", alarms):
                e.emit(
                    "etcd.alarms",
                    obj,
                    "etcd",
                    "high",
                    "snapshot",
                    "etcd 存在告警",
                    alarms[:1200],
                    "核对告警类型、配额和数据完整性，不自动解除告警。",
                    source="etcd/alarmlist",
                )
            else:
                e.check(
                    "etcd.alarms",
                    obj,
                    "unknown",
                    "etcd",
                    "告警输出无法识别：" + alarms[:200],
                    "etcd/alarmlist",
                )
        else:
            e.check("etcd.alarms", obj, "passed", "etcd")
    else:
        e.check("etcd.alarms", obj, "unknown", "etcd", "未采集告警输出")
    if not metric_sets:
        metric_sets = [("etcd/endpointstatus", {})]
    for path, values in metric_sets:
        metric_obj = {**obj, "id": identity(path), "analysisObjectKey": identity(path)}
        size, quota = values.get("etcd_mvcc_db_total_size_in_bytes"), values.get(
            "etcd_server_quota_backend_bytes"
        )
        e.metric(
            "etcd.etcdQuota",
            metric_obj,
            "etcd数据库/配额(%)",
            100 * size / quota if size is not None and quota and quota > 0 else None,
            category="etcd",
            source=path,
        )
        for key in (
            "etcd_server_leader_changes_seen_total",
            "etcd_server_proposals_failed_total",
        ):
            if key in values:
                e.emit(
                    "etcd.counter." + key,
                    metric_obj,
                    "etcd",
                    "info",
                    "snapshot",
                    "etcd 启动以来累计计数",
                    key + "=" + str(values[key]),
                    "单次累计值不能推算近期速率、选举频率或当前故障。",
                    source=path,
                    docs=DOCS["metrics"],
                )
