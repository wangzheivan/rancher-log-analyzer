import type { PageProps } from "./Browse";
import { useCatalog } from "../hooks";
import {
  Empty,
  Message,
  Pagination,
  Panel,
  Pill,
  SearchBox,
  Source,
} from "../components/Common";
function memory(raw?: string) {
  if (!raw) return "未知";
  const match = /^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti)?$/.exec(raw);
  if (!match) return raw;
  const n =
    Number(match[1]) *
    ({ Ki: 1024, Mi: 1024 ** 2, Gi: 1024 ** 3, Ti: 1024 ** 4 }[
      match[2] || ""
    ] || 1);
  return (n / 1024 ** 3).toFixed(1) + " GiB";
}
export function NodesPage({ bundle, nav, onSource }: PageProps) {
  const q = nav.params.get("q") || "",
    cursor = nav.params.get("cursor") || "";
  const { data, error, loading } = useCatalog(bundle, "nodes", {
    q,
    cursor,
    limit: 12,
  });
  return (
    <>
      <div className="toolbar">
        <SearchBox
          label="搜索节点"
          placeholder="搜索节点名称或 IP…"
          value={q}
          onChange={(q) => nav.set({ q, cursor: "" }, true)}
        />
      </div>
      <div className="note">
        容量与可分配资源来自 Node
        对象，不代表实时使用量。主机使用情况仅属于采集节点。
      </div>
      <Message error={error} loading={loading} />
      <div className="node-grid">
        {data?.items.map((n) => (
          <Panel
            key={n.id}
            title={
              <button
                className="link node-name"
                onClick={() => nav.go("node-detail", { id: n.id }, true)}
              >
                {n.name}
              </button>
            }
            action={
              <Pill tone={n.ready === "True" ? "good" : "warn"}>
                {n.ready === "True" ? "Ready" : "未知 / 未就绪"}
              </Pill>
            }
          >
            <div className="panel-body">
              <div className="muted mono">{n.ip || "未提供 IP"}</div>
              <div className="usage">
                <div>
                  <b>{n.capacity?.cpu || "未知"}</b>
                  <small>CPU 容量 / 核</small>
                </div>
                <div>
                  <b>{memory(n.capacity?.memory)}</b>
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
                <dd>{memory(n.allocatable?.memory)}</dd>
                <dt>Pod 容量</dt>
                <dd>{n.capacity?.pods || "未知"}</dd>
              </dl>
              <h3>节点 Conditions</h3>
              <div className="conditions">
                {n.conditions?.length ? (
                  n.conditions.map((c) => (
                    <Pill
                      key={c.type}
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
                  ))
                ) : (
                  <span className="muted">未提供 Conditions</span>
                )}
              </div>
              <div className="split-metric">
                <span>当前快照 Pod：{String(n.podCount ?? 0)}</span>
                <Source path={n.source} onOpen={onSource} />
              </div>
            </div>
          </Panel>
        ))}
      </div>
      {!loading && !data?.items.length && (
        <Empty>没有符合名称或 IP 的节点</Empty>
      )}
      <Pagination
        data={data}
        cursor={cursor}
        onCursor={(cursor) => nav.set({ cursor })}
      />
    </>
  );
}
