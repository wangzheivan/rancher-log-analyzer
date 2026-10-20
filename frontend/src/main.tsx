import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Archive,
  ArrowRight,
  Boxes,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileText,
  FolderOpen,
  HardDrive,
  LayoutDashboard,
  Layers,
  Network,
  Plus,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  Upload,
  X,
  Pencil,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { api, API, bytes, jsonBody, stateNames } from "./api";
import type {
  BundleRecord,
  Case,
  FileEntry,
  FilePage,
  Resource,
  Session,
  Summary,
} from "./types";
import "./style.css";
const pages = [
  {
    id: "overview",
    name: "采集概览",
    icon: LayoutDashboard,
    description: "从采集信息开始，了解集群的运行状态。",
  },
  {
    id: "nodes",
    name: "集群节点",
    icon: Server,
    description: "查看节点配置、容量与采集时刻的状态。",
  },
  {
    id: "pods",
    name: "Pod 工作负载",
    icon: Boxes,
    description: "按命名空间、节点与状态探索工作负载。",
  },
  {
    id: "resources",
    name: "资源快照",
    icon: Layers,
    description: "浏览采集时刻的 Kubernetes 资源清单。",
  },
  {
    id: "system",
    name: "主机与 etcd",
    icon: HardDrive,
    description: "当前采集节点的主机信息与 etcd 原始状态。",
  },
  {
    id: "files",
    name: "日志与文件",
    icon: FolderOpen,
    description: "按需读取原始文件，搜索日志中的关键线索。",
  },
];
const colors = [
  "#149b83",
  "#73a9cf",
  "#d8a448",
  "#8d86c6",
  "#ce7a82",
  "#6b8f9f",
];
const activeStates = ["uploading", "queued", "extracting", "parsing"];
function Pill({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="empty">
      <Archive size={30} />
      <div>{children}</div>
    </div>
  );
}
function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
function Source({
  path,
  onOpen,
}: {
  path: string;
  onOpen: (path: string) => void;
}) {
  return (
    <button className="link source-button" onClick={() => onOpen(path)}>
      <FileText size={12} /> 查看原文
    </button>
  );
}
function Pager({
  page,
  total,
  onPage,
}: {
  page: number;
  total: number;
  onPage: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>共 {total} 条 · 每页 50 条</span>
      <div>
        <button
          className="ghost"
          aria-label="上一页"
          disabled={!page}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft size={14} />
        </button>
        <span>
          {page + 1} / {Math.max(1, Math.ceil(total / 50))}
        </span>
        <button
          className="ghost"
          aria-label="下一页"
          disabled={(page + 1) * 50 >= total}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
function capacityMemory(value?: string) {
  if (!value) return "未知";
  const n = parseFloat(value);
  if (value.endsWith("Ki")) return `${(n / 1024 / 1024).toFixed(1)} GiB`;
  if (value.endsWith("Mi")) return `${(n / 1024).toFixed(1)} GiB`;
  return value;
}

function Overview({
  s,
  onPage,
  onOpen,
}: {
  s: Summary;
  onPage: (p: string) => void;
  onOpen: (p: string) => void;
}) {
  const ready = s.nodes.filter((n) => n.ready === "True").length,
    attention = s.pods.filter((p) => p.attention).length,
    running = s.podStatus.Running || 0;
  const nsCounts = s.namespaces
    .map((name) => ({
      name,
      count: s.pods.filter((p) => p.NAMESPACE === name).length,
    }))
    .sort((a, b) => b.count - a.count);
  const stats = [
    {
      label: "集群节点",
      value: s.nodes.length,
      unit: "个",
      foot: `${ready} Ready / ${s.nodes.length - ready} 其他或未知`,
      icon: Server,
    },
    {
      label: "Pod 工作负载",
      value: s.pods.length,
      unit: "个",
      foot: `${running} Running · ${s.podStatus.Completed || 0} Completed`,
      icon: Boxes,
    },
    {
      label: "命名空间",
      value:
        s.resources.find((r) => r.name === "namespaces")?.count ??
        s.namespaces.length,
      unit: "个",
      foot: "来自当前采集包的资源快照",
      icon: Network,
    },
    {
      label: "采集文件",
      value: s.files.length,
      unit: "份",
      foot: `${bytes(s.bytes)} · 原始数据按需读取`,
      icon: FileText,
    },
  ];
  return (
    <>
      <div className="summary-banner">
        <div className="banner-left">
          <span className="banner-icon">
            <ShieldCheck size={23} />
          </span>
          <div>
            <strong>
              {s.hostname} <span className="banner-separator">/</span>{" "}
              {s.distro.toUpperCase()} 集群快照
            </strong>
            <p>采集时间：{s.generated}</p>
          </div>
        </div>
        <Pill tone="blue">{s.version}</Pill>
      </div>
      {s.warnings.map((w) => (
        <div className="note warning" key={w}>
          {w}
        </div>
      ))}
      <div className="cards">
        {stats.map((c) => (
          <div className="stat" key={c.label}>
            <div className="stat-label">
              {c.label}
              <c.icon size={17} />
            </div>
            <div className="stat-value">
              {c.value} <small>{c.unit}</small>
            </div>
            <div className="stat-foot">{c.foot}</div>
          </div>
        ))}
      </div>
      <div className="grid">
        <Panel
          title="集群节点"
          action={
            <button className="link" onClick={() => onPage("nodes")}>
              全部节点 <ArrowRight size={12} />
            </button>
          }
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点 / INTERNAL IP</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>PODS</th>
                </tr>
              </thead>
              <tbody>
                {s.nodes.map((n) => (
                  <tr key={n.name}>
                    <td>
                      <strong>{n.name}</strong>
                      <div className="muted mono">{n.ip}</div>
                    </td>
                    <td>
                      <span className="role-label">{n.roles}</span>
                    </td>
                    <td>
                      <Pill tone={n.ready === "True" ? "good" : "warn"}>
                        {n.ready === "True" ? "Ready" : "未就绪 / 未知"}
                      </Pill>
                    </td>
                    <td>{s.pods.filter((p) => p.NODE === n.name).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!s.nodes.length && <Empty>未收集到节点信息</Empty>}
          <div className="source-line">
            来源：{s.distro}/kubectl/nodes.json 或 nodes
          </div>
        </Panel>
        <Panel
          title="Pod 状态分布"
          action={<span className="muted">采集快照</span>}
        >
          <div className="panel-body">
            <div className="status-heading">
              <div>
                <span className="big-number">{running}</span>
                <span className="muted"> / {s.pods.length} 运行中</span>
              </div>
              <Pill tone={!s.pods.length ? "" : attention ? "warn" : "good"}>
                {!s.pods.length ? "Pod 状态未知" : attention ? `${attention} 个状态需关注` : "未见异常 Pod 状态"}
              </Pill>
            </div>
            <div className="bars">
              {Object.entries(s.podStatus).map(([status, count], i) => (
                <span
                  key={status}
                  style={{
                    width: `${(count / Math.max(1, s.pods.length)) * 100}%`,
                    background: colors[i % colors.length],
                  }}
                />
              ))}
            </div>
            {Object.entries(s.podStatus).map(([status, count], i) => (
              <div className="legend-row" key={status}>
                <span>
                  <i style={{ background: colors[i % colors.length] }} />
                  {status}
                </span>
                <strong>{count}</strong>
              </div>
            ))}
            <div className="note pod-note">
              Completed 表示任务已完成；重启次数是历史累计值。
            </div>
          </div>
        </Panel>
      </div>
      <div className="grid">
        <Panel
          title="采集信息"
          action={<Source path="summary.txt" onOpen={onOpen} />}
        >
          <div className="panel-body">
            <dl className="meta">
              <dt>采集节点</dt>
              <dd>{s.hostname}</dd>
              <dt>操作系统</dt>
              <dd>{s.os}</dd>
              <dt>内核版本</dt>
              <dd className="mono">{s.kernel}</dd>
              <dt>Kubernetes</dt>
              <dd>{s.version}</dd>
              <dt>数据范围</dt>
              <dd>集群资源快照 + {s.hostname} 主机日志</dd>
            </dl>
          </div>
        </Panel>
        <Panel
          title="命名空间中的 Pod"
          action={
            <button className="link" onClick={() => onPage("pods")}>
              查看工作负载 <ArrowRight size={12} />
            </button>
          }
        >
          <div className="panel-body">
            {nsCounts.slice(0, 5).map((n, i) => (
              <div className="namespace-row" key={n.name}>
                <span>{n.name}</span>
                <div className="namespace-track">
                  <i
                    style={{
                      width: `${(n.count / Math.max(1, nsCounts[0]?.count)) * 100}%`,
                      background: colors[i % colors.length],
                    }}
                  />
                </div>
                <strong>{n.count}</strong>
              </div>
            ))}
            {!nsCounts.length && <p>未收集到 Pod 清单</p>}
          </div>
        </Panel>
      </div>
    </>
  );
}
function Nodes({ s, onOpen }: { s: Summary; onOpen: (p: string) => void }) {
  return (
    <>
      <div className="note">
        容量和可分配资源来自 Node
        对象，不代表实时使用量。主机使用信息仅在“主机与 etcd”中按采集节点展示。
      </div>
      <div className="node-grid">
        {s.nodes.map((n) => (
          <Panel
            key={n.name}
            title={n.name}
            action={
              <Pill tone={n.ready === "True" ? "good" : "warn"}>
                {n.ready === "True" ? "Ready" : "未就绪 / 未知"}
              </Pill>
            }
          >
            <div className="panel-body">
              <div className="muted mono">{n.ip}</div>
              <div className="usage">
                <div>
                  <b>{n.capacity.cpu || "未知"}</b>
                  <small>CPU 容量 / 核</small>
                </div>
                <div>
                  <b>{capacityMemory(n.capacity.memory)}</b>
                  <small>内存容量</small>
                </div>
              </div>
              <dl className="meta">
                <dt>角色</dt>
                <dd>{n.roles}</dd>
                <dt>Kubelet</dt>
                <dd>{n.kubeletVersion || "未知"}</dd>
                <dt>操作系统</dt>
                <dd>{n.osImage || "未知"}</dd>
                <dt>内核</dt>
                <dd>{n.kernelVersion || "未知"}</dd>
                <dt>容器运行时</dt>
                <dd>{n.containerRuntimeVersion || "未知"}</dd>
                <dt>可分配 CPU</dt>
                <dd>{n.allocatable?.cpu || "未知"}</dd>
                <dt>可分配内存</dt>
                <dd>{capacityMemory(n.allocatable?.memory)}</dd>
                <dt>Pod 容量</dt>
                <dd>{n.capacity.pods || "未知"}</dd>
              </dl>
              <h3>节点 Conditions</h3>
              <div className="conditions">
                {n.conditions.map((c) => (
                  <span
                    key={c.type}
                    title={`${c.reason || ""}\n${c.message || ""}`}
                  >
                    <Pill
                      tone={
                        (
                          c.type.endsWith("Pressure") ||
                          c.type === "NetworkUnavailable"
                            ? c.status === "False"
                            : c.status === "True"
                        )
                          ? "good"
                          : "warn"
                      }
                    >
                      {c.type}: {c.status}
                    </Pill>
                  </span>
                ))}
              </div>
              <div className="split-metric">
                <span>
                  当前快照 Pod：{s.pods.filter((p) => p.NODE === n.name).length}
                </span>
                <Source
                  path={s.files.some(f => f.path === `${s.distro}/kubectl/nodes.json`) ? `${s.distro}/kubectl/nodes.json` : `${s.distro}/kubectl/nodes`}
                  onOpen={onOpen}
                />
              </div>
            </div>
          </Panel>
        ))}
      </div>
      {!s.nodes.length && <Empty>未收集到节点信息</Empty>}
    </>
  );
}
function Pods({ s, onOpen }: { s: Summary; onOpen: (p: string) => void }) {
  const [q, setQ] = useState(""),
    [namespace, setNamespace] = useState(""),
    [node, setNode] = useState(""),
    [status, setStatus] = useState(""),
    [page, setPage] = useState(0);
  const rows = s.pods.filter(
    (p) =>
      (!q || `${p.NAME} ${p.IP}`.toLowerCase().includes(q.toLowerCase())) &&
      (!namespace || p.NAMESPACE === namespace) &&
      (!node || p.NODE === node) &&
      (!status || p.STATUS === status),
  );
  useEffect(() => setPage(0), [q, namespace, node, status]);
  return (
    <>
      <div className="toolbar">
        <div className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索 Pod"
            placeholder="搜索 Pod 名称或 IP…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <select
          aria-label="命名空间筛选"
          value={namespace}
          onChange={(e) => setNamespace(e.target.value)}
        >
          <option value="">全部命名空间</option>
          {s.namespaces.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
        <select
          aria-label="节点筛选"
          value={node}
          onChange={(e) => setNode(e.target.value)}
        >
          <option value="">全部节点</option>
          {s.nodes.map((n) => (
            <option key={n.name}>{n.name}</option>
          ))}
        </select>
        <select
          aria-label="状态筛选"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">全部状态</option>
          {Object.keys(s.podStatus).map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
      </div>
      <Panel
        title="Pod 清单"
        action={<Source path={s.resources.find(r => r.name === "pods")?.source || `${s.distro}/kubectl/pods`} onOpen={onOpen} />}
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>名称 / 命名空间</th>
                <th>就绪</th>
                <th>状态</th>
                <th>重启 / 最近一次</th>
                <th>节点</th>
                <th>AGE</th>
                <th>日志</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(page * 50, page * 50 + 50).map((p) => {
                const path = `${s.distro}/podlogs/${p.NAMESPACE}-${p.NAME}`,
                  current = s.files.find((f) => f.path === path),
                  previous = s.files.find((f) => f.path === `${path}-previous`);
                return (
                  <tr key={`${p.NAMESPACE}/${p.NAME}`}>
                    <td>
                      <strong>{p.NAME}</strong>
                      <div className="muted">{p.NAMESPACE}</div>
                    </td>
                    <td className="mono">{p.READY}</td>
                    <td>
                      <Pill
                        tone={
                          p.attention
                            ? "warn"
                            : p.STATUS === "Running"
                              ? "good"
                              : ""
                        }
                      >
                        {p.STATUS}
                      </Pill>
                    </td>
                    <td>{p.RESTARTS}</td>
                    <td>{p.NODE}</td>
                    <td>{p.AGE}</td>
                    <td>
                      <div className="table-actions">
                        {current && (
                          <button
                            className="link"
                            onClick={() => onOpen(current.path)}
                          >
                            当前
                          </button>
                        )}
                        {previous && (
                          <button
                            className="link"
                            onClick={() => onOpen(previous.path)}
                          >
                            上次
                          </button>
                        )}
                        {!current && !previous && (
                          <span className="muted">未收集</span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!rows.length && <Empty>没有符合条件的 Pod</Empty>}
        <Pager page={page} total={rows.length} onPage={setPage} />
      </Panel>
    </>
  );
}
function Resources({
  s,
  bundleId,
  onOpen,
}: {
  s: Summary;
  bundleId: string;
  onOpen: (p: string) => void;
}) {
  const [name, setName] = useState(
      s.resources.find((r) => r.name === "deployments")?.name ||
        s.resources[0]?.name ||
        "",
    ),
    [data, setData] = useState<Resource | null>(null),
    [q, setQ] = useState(""),
    [page, setPage] = useState(0),
    [error, setError] = useState("");
  useEffect(() => {
    if (!name) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    setPage(0);
    setQ("");
    api<Resource>(
      `/bundles/${bundleId}/resources/${encodeURIComponent(name)}`,
      { signal: controller.signal },
    )
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [name, bundleId]);
  useEffect(() => setPage(0), [q]);
  const rows =
    data?.rows.filter((r) =>
      Object.values(r).some((v) => v.toLowerCase().includes(q.toLowerCase())),
    ) || [];
  return (
    <div className="resource-layout">
      <div className="panel resource-menu" aria-label="资源类型">
        {s.resources.map((r) => (
          <button
            className={name === r.name ? "active" : ""}
            key={r.name}
            onClick={() => setName(r.name)}
          >
            <span>{r.name}</span>
            <small>{r.count}</small>
          </button>
        ))}
      </div>
      <div className="resource-content">
        <div className="toolbar">
          <div className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索资源"
              placeholder="筛选当前资源表…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>
        <Panel
          title={name || "资源快照"}
          action={data && <Source path={data.source} onOpen={onOpen} />}
        >
          {error ? (
            <div className="note warning">{error}</div>
          ) : !data ? (
            <Empty>{name ? "正在读取资源…" : "未收集到资源表"}</Empty>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {data.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(page * 50, page * 50 + 50).map((row, i) => (
                      <tr key={i}>
                        {data.columns.map((c) => (
                          <td key={c}>{row[c]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!rows.length && (
                <Empty>
                  {data.message === "No resources found"
                    ? "采集时未发现该类资源"
                    : data.message || "没有符合条件的资源"}
                </Empty>
              )}
              {!!data.skipped && (
                <div className="note warning">
                  有 {data.skipped} 行未能解析，请查看原文。
                </div>
              )}
              <Pager page={page} total={rows.length} onPage={setPage} />
              <div className="source-line">来源：{data.source}</div>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
function System({ s, onOpen }: { s: Summary; onOpen: (p: string) => void }) {
  return (
    <>
      <div className="note">
        以下主机数据仅属于采集节点 <strong>{s.hostname}</strong>。etcd
        输出也只代表本包收集到的端点，不推断整个集群健康。
      </div>
      <div className="grid">
        {[
          ["freeh", "内存使用"],
          ["dfh", "磁盘与挂载"],
          ["uptime", "运行时间与负载"],
          ["lscpu", "CPU 信息"],
        ].map(([key, label]) => (
          <Panel
            key={key}
            title={label}
            action={<Source path={`systeminfo/${key}`} onOpen={onOpen} />}
          >
            <div className="panel-body">
              {s.system[key] ? (
                <pre className="compact-pre">{s.system[key]}</pre>
              ) : (
                <p>未收集或文件为空</p>
              )}
            </div>
          </Panel>
        ))}
      </div>
      <div className="grid">
        {[
          ["endpointhealth", "etcd 端点健康"],
          ["endpointstatus", "etcd 端点状态"],
          ["memberlist", "etcd 成员"],
          ["alarmlist", "etcd 告警"],
        ].map(([key, label]) => (
          <Panel
            key={key}
            title={label}
            action={<Source path={`etcd/${key}`} onOpen={onOpen} />}
          >
            <div className="panel-body">
              {s.etcd[key] ? (
                <pre className="compact-pre">{s.etcd[key]}</pre>
              ) : (
                <p>
                  {s.files.some((f) => f.path === `etcd/${key}`)
                    ? "文件为空，未记录输出"
                    : "未收集该项信息"}
                </p>
              )}
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}
function Files({ s, onOpen }: { s: Summary; onOpen: (p: string) => void }) {
  const [q, setQ] = useState(""),
    [category, setCategory] = useState(""),
    [page, setPage] = useState(0);
  const rows = s.files.filter(
    (f) =>
      (!category || f.category === category) &&
      f.path.toLowerCase().includes(q.toLowerCase()),
  );
  useEffect(() => setPage(0), [q, category]);
  return (
    <>
      <div className="toolbar">
        <div className="search-field">
          <Search size={16} />
          <input
            aria-label="搜索文件"
            placeholder="按路径或文件名筛选，例如 kubelet、podlogs…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>
      <div className="category-strip">
        {["", ...new Set(s.files.map((f) => f.category))].map((c) => (
          <button
            key={c}
            className={`chip ${category === c ? "active" : ""}`}
            onClick={() => setCategory(c)}
          >
            {c || "全部文件"}{" "}
            <span>{s.files.filter((f) => !c || f.category === c).length}</span>
          </button>
        ))}
      </div>
      <Panel
        title="原始文件"
        action={<span className="muted">{bytes(s.bytes)} · 按需加载</span>}
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>文件路径</th>
                <th>分类</th>
                <th>大小</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(page * 50, page * 50 + 50).map((f) => (
                <tr key={f.id}>
                  <td className="file-path mono">
                    <button
                      className="link file-link"
                      onClick={() => onOpen(f.path)}
                    >
                      <FileText size={14} />
                      {f.path}
                    </button>
                  </td>
                  <td>
                    <Pill>{f.category}</Pill>
                  </td>
                  <td className="mono">{bytes(f.size)}</td>
                  <td>
                    <button className="link" onClick={() => onOpen(f.path)}>
                      查看 <ExternalLink size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && <Empty>没有符合条件的文件</Empty>}
        <Pager page={page} total={rows.length} onPage={setPage} />
      </Panel>
    </>
  );
}
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let start = 0,
    index = 0;
  const lower = text.toLowerCase(),
    needle = query.toLowerCase();
  while ((index = lower.indexOf(needle, start)) !== -1) {
    parts.push(
      text.slice(start, index),
      <mark key={index}>{text.slice(index, index + query.length)}</mark>,
    );
    start = index + query.length;
  }
  parts.push(text.slice(start));
  return <>{parts}</>;
}
function Viewer({
  file,
  bundleId,
  onClose,
}: {
  file: FileEntry;
  bundleId: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null),
    [draft, setDraft] = useState(""),
    [query, setQuery] = useState(""),
    [offset, setOffset] = useState(0),
    [history, setHistory] = useState<number[]>([]),
    [data, setData] = useState<FilePage | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api<FilePage>(
      `/bundles/${bundleId}/files/${file.id}?offset=${offset}&q=${encodeURIComponent(query)}`,
      { signal: controller.signal },
    )
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [file.id, bundleId, offset, query]);
  const search = (value: string) => {
    setQuery(value);
    setOffset(0);
    setHistory([]);
  };
  return (
    <dialog id="viewer" ref={ref} onCancel={onClose}>
      <div className="viewer-head">
        <div>
          <div className="eyebrow">SOURCE FILE / {bytes(file.size)}</div>
          <h2>{file.path}</h2>
        </div>
        <button className="ghost" onClick={onClose} aria-label="关闭文件">
          <X size={18} />
        </button>
      </div>
      <form
        id="log-search"
        onSubmit={(e) => {
          e.preventDefault();
          search(draft);
        }}
      >
        <input
          aria-label="日志关键字"
          maxLength={500}
          placeholder="搜索当前文件内容（不区分大小写）"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="primary" disabled={busy}>
          <Search size={14} /> 搜索
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            setDraft("");
            search("");
          }}
        >
          重置
        </button>
      </form>
      <div className="muted">
        每次扫描最多 2 MiB，展示最多 250
        条；超长行分段显示，使用“继续”浏览后续内容。
      </div>
      {error && <div className="note warning">{error}</div>}
      <pre id="log-content" tabIndex={0} aria-label="文件内容">
        {busy
          ? "正在读取…"
          : data?.binary
            ? "此文件包含二进制内容，仅展示文件元信息。"
            : data?.lines.length
              ? data.lines.map((line, i) => (
                  <span className="log-line" key={i}>
                    <span className="log-offset" title="字节位置">
                      {data.segments[i].offset}
                    </span>
                    <span>
                      <Highlight text={line} query={query} />
                      {data.segments[i].continued && (
                        <span className="segment-label"> [长行分段 →]</span>
                      )}
                    </span>
                  </span>
                ))
              : query
                ? data?.hasMore ? "本次扫描未找到匹配内容。可继续搜索文件后续部分。" : "已扫描至文件末尾，未找到匹配内容。"
                : "文件为空。"}
      </pre>
      <div className="viewer-bottom">
        <span>
          {data
            ? `${bytes(data.nextOffset)} / ${bytes(data.size)} · 本次 ${data.lines.length} 条`
            : "读取中…"}
        </span>
        <div className="table-actions">
          <button
            className="ghost"
            disabled={busy || !history.length}
            onClick={() => {
              setOffset(history[history.length - 1]);
              setHistory(history.slice(0, -1));
            }}
          >
            上一块
          </button>
          <button
            className="primary"
            disabled={busy || !data?.hasMore}
            onClick={() => {
              setHistory([...history, offset]);
              setOffset(data!.nextOffset);
            }}
          >
            {query ? "继续搜索" : "继续读取"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
function App() {
  const [cases, setCases] = useState<Case[]>([]),
    [caseId, setCaseId] = useState(""),
    [bundleId, setBundleId] = useState(""),
    [summary, setSummary] = useState<Summary | null>(null),
    [page, setPage] = useState("overview"),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [session, setSession] = useState<Session | null>(null),
    [viewer, setViewer] = useState<FileEntry | null>(null);
  const [caseModal, setCaseModal] = useState<"create" | "rename" | null>(null),
    [caseName, setCaseName] = useState(""),
    [saving, setSaving] = useState(false),
    [upload, setUpload] = useState<{ name: string; progress: number } | null>(
      null,
    ),
    [manage, setManage] = useState(false);
  const xhrRef = useRef<XMLHttpRequest | null>(null),
    fileRef = useRef<HTMLInputElement>(null),
    caseDialog = useRef<HTMLDialogElement>(null);
  const currentCase = cases.find((c) => c.id === caseId),
    bundles = currentCase?.bundles || [],
    currentBundle = bundles.find((b) => b.id === bundleId),
    currentPage = pages.find((p) => p.id === page)!;
  const refresh = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api<Case[]>("/cases"),
        api<Session>("/session"),
      ]);
      setCases(c);
      setSession(s);
      setLoading(false);
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 1500);
    return () => clearInterval(interval);
  }, [refresh]);
  useEffect(() => {
    if (!cases.some((c) => c.id === caseId)) {
      setCaseId(cases[0]?.id || "");
      setBundleId("");
    }
  }, [cases, caseId]);
  useEffect(() => {
    if (!bundles.some((b) => b.id === bundleId))
      setBundleId(bundles[0]?.id || "");
  }, [bundles, bundleId]);
  useEffect(() => {
    setSummary(null);
    setViewer(null);
    if (!bundleId || currentBundle?.state !== "ready") return;
    const controller = new AbortController();
    api<Summary>(`/bundles/${bundleId}/summary`, { signal: controller.signal })
      .then(setSummary)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [bundleId, currentBundle?.state]);
  useEffect(() => {
    if (caseModal) caseDialog.current?.showModal();
  }, [caseModal]);
  function openFile(path: string) {
    const file = summary?.files.find((f) => f.path === path);
    if (file) setViewer(file);
    else setError(`当前采集包未包含文件：${path}`);
  }
  async function saveCase(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const c = await api<Case>(
        caseModal === "rename" ? `/cases/${caseId}` : "/cases",
        {
          method: caseModal === "rename" ? "PATCH" : "POST",
          ...jsonBody({ name: caseName }),
        },
      );
      await refresh();
      setCaseId(c.id);
      setBundleId("");
      setCaseModal(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function deleteCase() {
    if (
      !currentCase ||
      !window.confirm(
        `删除案例“${currentCase.name}”及其全部采集数据？此操作无法恢复。`,
      )
    )
      return;
    try {
      await api(`/cases/${caseId}`, { method: "DELETE" });
      setSummary(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function deleteBundle(b: BundleRecord) {
    if (
      !window.confirm(
        `${activeStates.includes(b.state) ? "取消导入并删除" : "删除"}采集包“${b.name}”？`,
      )
    )
      return;
    try {
      await api(`/bundles/${b.id}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function uploadFiles(files: FileList | null) {
    if (!files || !caseId) return;
    const targetCase = caseId;
    setError("");
    try {
      for (const file of Array.from(files)) {
        if (!/\.(tar\.gz|tgz)$/i.test(file.name))
          throw new Error("仅支持 .tar.gz 或 .tgz 采集包");
        if (session && file.size > session.maxUploadBytes)
          throw new Error(
            `单包压缩大小不能超过 ${bytes(session.maxUploadBytes)}`,
          );
        setUpload({ name: file.name, progress: 0 });
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhrRef.current = xhr;
          xhr.open(
            "POST",
            `${API}/cases/${targetCase}/bundles?filename=${encodeURIComponent(file.name)}`,
          );
          xhr.setRequestHeader("Content-Type", "application/gzip");
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable)
              setUpload({
                name: file.name,
                progress: Math.round((e.loaded / e.total) * 100),
              });
          };
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve();
            else {
              let message = `上传失败（${xhr.status}）`;
              try {
                message = JSON.parse(xhr.responseText).detail || message;
              } catch {}
              reject(new Error(message));
            }
          };
          xhr.onerror = () => reject(new Error("上传连接失败，请检查服务状态"));
          xhr.onabort = () => reject(new Error("上传已取消"));
          xhr.send(file);
        });
        await refresh();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUpload(null);
      xhrRef.current = null;
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  return (
    <>
      <aside>
        <a
          className="brand"
          href="#overview"
          onClick={() => setPage("overview")}
        >
          <span className="brand-icon">
            <Activity size={27} />
          </span>
          <div>
            RANCHER<span>SUPPORT EXPLORER</span>
          </div>
        </a>
        <div className="workspace-label">离线诊断工作台</div>
        <nav aria-label="主导航">
          {pages.map((p) => (
            <button
              key={p.id}
              data-page={p.id}
              className={page === p.id ? "active" : ""}
              onClick={() => setPage(p.id)}
            >
              <p.icon size={18} />
              <span>{p.name}</span>
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <span className="live-dot" /> 集群内离线分析
          <p>
            原始日志按需读取
            <br />
            采集快照 · 非实时监控
          </p>
          <small>RANCHER LOG EXPLORER / V0.1</small>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div className="breadcrumb">
            工作空间 <span>/</span> {currentCase?.name || "案例管理"}{" "}
            <span>/</span> <strong>{currentPage.name}</strong>
          </div>
          <span className="offline">
            <ShieldCheck size={12} /> 临时共享工作区
          </span>
        </header>
        <main>
          <div className="heading">
            <div>
              <div className="eyebrow">SUPPORT BUNDLE EXPLORER</div>
              <h1>{currentPage.name}</h1>
              <p>{currentPage.description}</p>
            </div>
            <button
              className="primary"
              onClick={() => {
                setCaseName("");
                setCaseModal("create");
              }}
            >
              <Plus size={15} /> 新建案例
            </button>
          </div>
          <div className="workspace-notice">
            <CircleHelp size={15} />
            <span>
              临时共享工作区：所有访问者可查看和删除案例，服务重启将清空全部上传数据。
            </span>
            <span className="storage-meter">
              {session
                ? `${bytes(session.usedBytes)} / ${bytes(session.maxSessionBytes)}`
                : ""}
            </span>
          </div>
          {error && (
            <div id="error" role="alert">
              <span>{error}</span>
              <button
                className="link"
                aria-label="关闭提示"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {loading ? (
            <Empty>正在连接工作区…</Empty>
          ) : (
            <>
              <div className="selection-bar">
                <div className="selection-field">
                  <label htmlFor="case-select">当前案例</label>
                  <div className="table-actions">
                    <select
                      id="case-select"
                      value={caseId}
                      onChange={(e) => {
                        setCaseId(e.target.value);
                        setBundleId("");
                        setManage(false);
                      }}
                      disabled={!!upload}
                    >
                      <option value="" disabled>
                        选择案例
                      </option>
                      {cases.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    <button
                      className="icon-button"
                      aria-label="重命名案例"
                      disabled={!currentCase || !!upload}
                      onClick={() => {
                        setCaseName(currentCase!.name);
                        setCaseModal("rename");
                      }}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      className="icon-button danger"
                      aria-label="删除案例"
                      disabled={!currentCase || !!upload}
                      onClick={() => void deleteCase()}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                <div className="selection-field bundle-field">
                  <label htmlFor="bundle-select">
                    采集包 · {bundles.length} 份
                  </label>
                  <select
                    id="bundle-select"
                    value={bundleId}
                    onChange={(e) => setBundleId(e.target.value)}
                  >
                    <option value="" disabled>
                      选择采集包
                    </option>
                    {bundles.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.hostname || b.name} ·{" "}
                        {b.generated || stateNames[b.state]}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="selection-actions">
                  <button
                    className="ghost"
                    disabled={!currentCase}
                    onClick={() => setManage(!manage)}
                  >
                    <Archive size={14} /> 管理采集包
                  </button>
                  <button
                    className="primary"
                    disabled={!currentCase || !!upload}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Upload size={14} /> 上传采集包
                  </button>
                  <input
                    hidden
                    ref={fileRef}
                    type="file"
                    aria-label="上传采集包文件"
                    accept=".tar.gz,.tgz"
                    multiple
                    onChange={(e) => void uploadFiles(e.target.files)}
                  />
                </div>
              </div>
              {upload && (
                <div className="upload-progress">
                  <Loader2 size={17} className="spin" />
                  <span>
                    正在上传 {upload.name} · {upload.progress}%
                  </span>
                  <progress value={upload.progress} max={100} />
                  <button
                    className="link"
                    onClick={() => xhrRef.current?.abort()}
                  >
                    取消上传
                  </button>
                </div>
              )}
              {manage && currentCase && (
                <Panel
                  title="案例内采集包"
                  action={
                    <button className="link" onClick={() => setManage(false)}>
                      收起
                    </button>
                  }
                >
                  {bundles.map((b) => (
                    <div className="bundle-row" key={b.id}>
                      <button
                        className="link bundle-name"
                        onClick={() => setBundleId(b.id)}
                      >
                        {b.name}
                        <small>
                          {b.hostname || "等待解析"} · {b.generated || "—"}
                        </small>
                      </button>
                      <Pill
                        tone={
                          b.state === "ready"
                            ? "good"
                            : b.state === "failed"
                              ? "bad"
                              : "blue"
                        }
                      >
                        {stateNames[b.state]}
                      </Pill>
                      <span className="bundle-error">{b.error}</span>
                      <button
                        className="icon-button danger"
                        aria-label={`删除采集包 ${b.name}`}
                        onClick={() => void deleteBundle(b)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                  {!bundles.length && <Empty>尚未上传采集包</Empty>}
                </Panel>
              )}
              {!currentCase ? (
                <div className="welcome">
                  <div className="welcome-art">
                    <Archive size={40} />
                    <div className="art-line" />
                    <Server size={24} />
                    <Boxes size={24} />
                    <FileText size={24} />
                  </div>
                  <div className="eyebrow">START WITH A SUPPORT BUNDLE</div>
                  <h2>让采集信息，变得一目了然</h2>
                  <p>
                    创建一个排障案例，上传 Rancher 官方采集包。
                    <br />
                    从集群状态到原始日志，在一个工作台中探索。
                  </p>
                  <button
                    className="primary"
                    onClick={() => {
                      setCaseName("");
                      setCaseModal("create");
                    }}
                  >
                    <Plus size={16} /> 创建第一个案例
                  </button>
                  <div className="welcome-features">
                    <span>
                      <Check size={14} /> RKE2 / K3s / RKE / kubeadm
                    </span>
                    <span>
                      <Check size={14} /> 多节点案例管理
                    </span>
                    <span>
                      <Check size={14} /> 数据留在部署环境
                    </span>
                  </div>
                </div>
              ) : !currentBundle ? (
                <div className="welcome">
                  <Upload size={36} />
                  <h2>为“{currentCase.name}”添加采集数据</h2>
                  <p>
                    上传官方 .tar.gz 或 .tgz 文件，可选择多个节点采集包。
                    <br />
                    单包压缩上限 {bytes(session?.maxUploadBytes || 1024 ** 3)}
                    ，解压上限 {bytes(session?.maxUnpackBytes || 5 * 1024 ** 3)}
                    。
                  </p>
                  <button
                    className="primary"
                    disabled={!!upload}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Upload size={15} /> 选择采集包
                  </button>
                </div>
              ) : currentBundle.state !== "ready" ? (
                <Panel title={currentBundle.name}>
                  <div className="processing">
                    {currentBundle.state === "failed" ? (
                      <Archive size={32} />
                    ) : (
                      <Loader2 size={32} className="spin" />
                    )}
                    <h2>{stateNames[currentBundle.state]}</h2>
                    <p>
                      {currentBundle.error ||
                        "正在后台处理采集包，完成后会自动显示数据。"}
                    </p>
                    <button
                      className="ghost"
                      onClick={() => void deleteBundle(currentBundle)}
                    >
                      {currentBundle.state === "failed"
                        ? "删除失败记录"
                        : "取消导入并删除"}
                    </button>
                  </div>
                </Panel>
              ) : !summary ? (
                <Empty>正在加载采集摘要…</Empty>
              ) : (
                <div key={bundleId} id="content">
                  {page === "overview" && (
                    <Overview s={summary} onPage={setPage} onOpen={openFile} />
                  )}
                  {page === "nodes" && <Nodes s={summary} onOpen={openFile} />}
                  {page === "pods" && <Pods s={summary} onOpen={openFile} />}
                  {page === "resources" && (
                    <Resources
                      s={summary}
                      bundleId={bundleId}
                      onOpen={openFile}
                    />
                  )}
                  {page === "system" && (
                    <System s={summary} onOpen={openFile} />
                  )}
                  {page === "files" && <Files s={summary} onOpen={openFile} />}
                </div>
              )}
            </>
          )}
          <footer>
            <span>基于 Rancher 官方日志收集器输出</span>
            <span>快照中的状态仅代表采集时刻</span>
          </footer>
        </main>
      </div>
      {viewer && (
        <Viewer
          key={`${bundleId}/${viewer.id}`}
          file={viewer}
          bundleId={bundleId}
          onClose={() => setViewer(null)}
        />
      )}
      {caseModal && (
        <dialog
          ref={caseDialog}
          className="case-dialog"
          onCancel={() => setCaseModal(null)}
        >
          <form onSubmit={(e) => void saveCase(e)}>
            <div className="viewer-head">
              <h2>{caseModal === "create" ? "新建排障案例" : "重命名案例"}</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="关闭案例窗口"
                onClick={() => setCaseModal(null)}
              >
                <X size={18} />
              </button>
            </div>
            <label htmlFor="case-name">案例名称</label>
            <input
              id="case-name"
              autoFocus
              required
              maxLength={100}
              value={caseName}
              placeholder="例如：生产集群网络排查"
              onChange={(e) => setCaseName(e.target.value)}
            />
            <p>将同一问题涉及的节点采集包放在一个案例中。</p>
            <div className="dialog-actions">
              <button
                type="button"
                className="ghost"
                onClick={() => setCaseModal(null)}
              >
                取消
              </button>
              <button className="primary" disabled={saving || !caseName.trim()}>
                {saving ? "保存中…" : "保存案例"}
              </button>
            </div>
          </form>
        </dialog>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
