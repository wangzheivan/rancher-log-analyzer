import type { PageProps } from "./Browse";
import { Panel, Pill, Source } from "../components/Common";
import { bytes } from "../api";
import { Server, Boxes, Network, FileText, ShieldCheck } from "lucide-react";
const colors = ["#149b83", "#73a9cf", "#d8a448", "#8d86c6"];
export function OverviewPage({ overview: s, nav, onSource }: PageProps) {
  const running = s.podStatus.Running || 0;
  const stats = [
    {
      label: "集群节点",
      value: s.counts.nodes,
      unit: "个",
      foot: `${s.readyNodes} Ready`,
      icon: Server,
    },
    {
      label: "Pod 工作负载",
      value: s.counts.pods,
      unit: "个",
      foot: `${running} Running · ${s.podStatus.Completed || 0} Completed`,
      icon: Boxes,
    },
    {
      label: "命名空间",
      value: s.counts.namespaces,
      unit: "个",
      foot: "当前采集包中的资源快照",
      icon: Network,
    },
    {
      label: "采集文件",
      value: s.counts.files,
      unit: "份",
      foot: bytes(s.bytes) + " · 按需读取",
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
              {s.hostname} / {s.distro.toUpperCase()} 集群快照
            </strong>
            <p>采集时间：{s.generated}</p>
          </div>
        </div>
        <Pill tone="blue">{s.version}</Pill>
      </div>
      {s.warnings.slice(0, 3).map((w) => (
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
          title="节点预览 · 最多10个"
          action={
            <button className="link" onClick={() => nav.go("nodes")}>
              全部节点 →
            </button>
          }
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点 / IP</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>PODS</th>
                </tr>
              </thead>
              <tbody>
                {s.nodePreview.map((n) => (
                  <tr key={n.id}>
                    <td>
                      <button
                        className="link"
                        onClick={() =>
                          nav.go("node-detail", { id: n.id }, true)
                        }
                      >
                        {n.name}
                      </button>
                      <div className="muted mono">{n.ip}</div>
                    </td>
                    <td>{n.roles}</td>
                    <td>
                      <Pill tone={n.ready === "True" ? "good" : "warn"}>
                        {n.ready === "True" ? "Ready" : "未知/未就绪"}
                      </Pill>
                    </td>
                    <td>{String(n.podCount ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Pod 状态与日志覆盖">
          <div className="panel-body">
            <span className="big-number">{running}</span>
            <span className="muted"> / {s.counts.pods} Running</span>
            <div className="bars">
              {Object.entries(s.podStatus).map(([status, count], i) => (
                <span
                  key={status}
                  style={{
                    width: `${(100 * count) / Math.max(s.counts.pods, 1)}%`,
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
            <div className="note">
              {s.podLogCoverage} / {s.counts.pods} 个快照 Pod
              关联了采集日志。日志覆盖情况不代表集群健康。
            </div>
            <button className="link" onClick={() => nav.go("completeness")}>
              查看采集完整性 →
            </button>
          </div>
        </Panel>
      </div>
      <div className="grid">
        <Panel
          title="采集信息"
          action={<Source path="summary.txt" onOpen={onSource} />}
        >
          <div className="panel-body">
            <dl className="meta">
              <dt>节点</dt>
              <dd>{s.hostname}</dd>
              <dt>系统</dt>
              <dd>{s.os}</dd>
              <dt>内核</dt>
              <dd>{s.kernel}</dd>
              <dt>版本</dt>
              <dd>{s.version}</dd>
              <dt>数据范围</dt>
              <dd>集群资源快照 + 当前采集节点数据</dd>
            </dl>
          </div>
        </Panel>
        <Panel title="命名空间中的 Pod · Top10">
          <div className="panel-body">
            {s.namespaceDistribution.map((n, i) => (
              <div className="namespace-row" key={n.name}>
                <span>{n.name}</span>
                <div className="namespace-track">
                  <i
                    style={{
                      width: `${(100 * n.count) / Math.max(1, s.namespaceDistribution[0]?.count)}%`,
                      background: colors[i % colors.length],
                    }}
                  />
                </div>
                <strong>{n.count}</strong>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
export function SystemPage({ overview: s, onSource }: PageProps) {
  return (
    <>
      <div className="note">
        主机数据只属于 {s.hostname}。每张卡片预览最多8
        KiB，完整数据可通过原文读取。
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
            action={<Source path={"systeminfo/" + key} onOpen={onSource} />}
          >
            <div className="panel-body">
              <pre className="compact-pre">
                {s.system[key] || "未收集或文件为空"}
              </pre>
            </div>
          </Panel>
        ))}
        {[
          ["endpointhealth", "etcd 端点健康"],
          ["endpointstatus", "etcd 端点状态"],
          ["memberlist", "etcd 成员"],
          ["alarmlist", "etcd 告警"],
        ].map(([key, label]) => (
          <Panel
            key={key}
            title={label}
            action={<Source path={"etcd/" + key} onOpen={onSource} />}
          >
            <div className="panel-body">
              <pre className="compact-pre">
                {s.etcd[key] || "未提供有效输出，请核对采集完整性。"}
              </pre>
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}
