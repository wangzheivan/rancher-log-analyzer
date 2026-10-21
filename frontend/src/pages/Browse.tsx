import type { Navigation } from "../hooks";
import { useCatalog } from "../hooks";
import type { Item, Overview } from "../model";
import {
  AsyncSelect,
  Empty,
  Message,
  Pagination,
  Panel,
  Pill,
  SearchBox,
  Source,
  statuses,
  value,
} from "../components/Common";
import { bytes } from "../api";
export interface PageProps {
  bundle: string;
  nav: Navigation;
  overview: Overview;
  onSource: (path: string, offset?: number) => void;
}
export function BrowsePage({
  bundle,
  nav,
  overview,
  onSource,
  kind,
}: { kind: "pods" | "nodes" | "files" | "resources" | "events" } & PageProps) {
  const p = nav.params;
  const filter = (values: Record<string, string>) =>
    nav.set({ ...values, cursor: "" }, true);
  const resource =
    kind === "resources"
      ? p.get("resource") ||
        overview.resources.find((r) => r.name === "deployments")?.name ||
        overview.resources[0]?.name ||
        ""
      : "";
  const query = {
    cursor: p.get("cursor") || "",
    q: p.get("q") || "",
    namespace: p.get("namespace") || "",
    node: p.get("node") || "",
    status: p.get("status") || "",
    resource,
    object_name: p.get("object_name") || "",
    object_kind: p.get("object_kind") || "",
    object_uid: p.get("object_uid") || "",
    reason: p.get("reason") || "",
    limit: 50,
  };
  const { data, error, loading } = useCatalog(bundle, kind, query);
  const columns =
    kind === "pods"
      ? ["Pod / 命名空间", "就绪 / 状态", "节点", "重启 / AGE", "采集日志"]
      : kind === "nodes"
        ? ["节点 / IP", "角色", "状态", "版本 / 系统", "容量"]
        : kind === "files"
          ? ["文件路径", "分类", "大小", "操作"]
          : kind === "events"
            ? ["类型 / 原因", "关联对象", "时间 / 次数", "消息 / 关联依据"]
            : [];
  const first = data?.items[0];
  const upper = first
    ? Object.keys(first).filter((k) => k.toUpperCase() === k)
    : [];
  const resourceColumns = upper.length
    ? upper
    : first
      ? Object.keys(first).filter(
          (k) => !["id", "source"].includes(k) && typeof first[k] !== "object",
        )
      : [];
  function log(row: Item) {
    nav.go(
      "pod-logs",
      {
        namespace: row.namespace || "",
        pod: row.logPodId || "",
        podName: row.name,
        file: row.logFileId || "",
      },
      true,
    );
  }
  return (
    <>
      <div className="toolbar">
        <SearchBox
          label={
            kind === "pods"
              ? "搜索 Pod"
              : kind === "files"
                ? "搜索文件"
                : "搜索列表"
          }
          placeholder="输入名称、路径或关键字…"
          value={query.q}
          onChange={(q) => filter({ q })}
        />
        {(kind === "pods" || kind === "events" || kind === "resources") && (
          <AsyncSelect
            bundle={bundle}
            kind="namespaces"
            label="命名空间"
            value={query.namespace}
            onChange={(namespace) => filter({ namespace })}
          />
        )}
        {kind === "pods" && (
          <AsyncSelect
            bundle={bundle}
            kind="nodes"
            label="节点"
            nameValue
            value={query.node}
            onChange={(node) => filter({ node })}
          />
        )}
        {kind === "pods" && (
          <select
            aria-label="状态筛选"
            value={query.status}
            onChange={(e) => filter({ status: e.target.value })}
          >
            <option value="">全部状态</option>
            {Object.keys(overview.podStatus).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        )}
        {kind === "events" && (
          <>
            <input
              aria-label="事件原因"
              placeholder="原因（精确匹配）"
              value={query.reason}
              onChange={(e) => filter({ reason: e.target.value })}
            />
            <input
              aria-label="事件对象名称"
              placeholder="对象名称（精确匹配）"
              value={query.object_name}
              onChange={(e) =>
                filter({ object_name: e.target.value, object_uid: "" })
              }
            />
          </>
        )}
        {kind === "events" && (
          <select
            aria-label="事件类型"
            value={query.status}
            onChange={(e) => filter({ status: e.target.value })}
          >
            <option value="">全部类型</option>
            <option>Warning</option>
            <option>Normal</option>
          </select>
        )}
      </div>
      {kind === "events" && (query.object_name || query.object_kind) && (
        <div className="note">
          当前关联：{query.object_kind} / {query.object_name}{" "}
          {query.object_uid ? "· UID 优先，名称匹配明确标记" : ""}
          <button
            className="link"
            onClick={() =>
              filter({ object_name: "", object_kind: "", object_uid: "" })
            }
          >
            清除对象筛选
          </button>
        </div>
      )}
      <div className={kind === "resources" ? "resource-layout" : ""}>
        {kind === "resources" && (
          <AsyncSelect
            bundle={bundle}
            kind="resources"
            label="资源类型"
            nameValue
            selectedLabel={resource}
            value={resource}
            onChange={(resource) => filter({ resource, q: "" })}
          />
        )}
        <div className="browse-content">
          <Panel
            title={
              kind === "pods"
                ? "Pod 清单"
                : kind === "nodes"
                  ? "集群节点"
                  : kind === "files"
                    ? "原始文件"
                    : kind === "events"
                      ? "事件浏览"
                      : resource
            }
            action={
              <Source
                path={
                  kind === "resources"
                    ? data?.source
                    : kind === "pods"
                      ? overview.resources.find((r) => r.name === "pods")
                          ?.source
                      : kind === "nodes"
                        ? overview.resources.find((r) => r.name === "nodes")
                            ?.source
                        : kind === "events"
                          ? overview.resources.find((r) => r.name === "events")
                              ?.source
                          : undefined
                }
                onOpen={onSource}
              />
            }
          >
            <Message error={error} loading={loading} />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {(kind === "resources" ? resourceColumns : columns).map(
                      (c) => (
                        <th key={c}>{c}</th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((row, i) => (
                    <tr key={row.id || i}>
                      {kind === "pods" && (
                        <>
                          <td>
                            <button
                              className="link entity-link"
                              onClick={() =>
                                nav.go("pod-detail", { id: row.id }, true)
                              }
                            >
                              {row.name}
                            </button>
                            <div className="muted">{row.namespace}</div>
                          </td>
                          <td>
                            <span className="mono">{row.ready}</span>
                            <br />
                            <Pill
                              tone={
                                row.attention
                                  ? "warn"
                                  : row.status === "Running"
                                    ? "good"
                                    : ""
                              }
                            >
                              {row.status}
                            </Pill>
                          </td>
                          <td>{row.node || "未提供"}</td>
                          <td>
                            {value(row.RESTARTS)}
                            <div className="muted">{value(row.AGE)}</div>
                          </td>
                          <td>
                            {row.logCount ? (
                              <>
                                <button
                                  className="link"
                                  onClick={() => log(row)}
                                >
                                  查看日志 · {row.logCount}
                                </button>
                                <div className="muted">
                                  {statuses[row.logState || ""] || row.logState}
                                </div>
                              </>
                            ) : (
                              <span className="muted">当前包未发现日志</span>
                            )}
                          </td>
                        </>
                      )}
                      {kind === "nodes" && (
                        <>
                          <td>
                            <button
                              className="link entity-link"
                              onClick={() =>
                                nav.go("node-detail", { id: row.id }, true)
                              }
                            >
                              {row.name}
                            </button>
                            <div className="muted mono">{row.ip}</div>
                          </td>
                          <td>{row.roles}</td>
                          <td>
                            <Pill tone={row.ready === "True" ? "good" : "warn"}>
                              {row.ready === "True" ? "Ready" : "未就绪/未知"}
                            </Pill>
                          </td>
                          <td>
                            {row.kubeletVersion}
                            <div className="muted">{row.osImage}</div>
                          </td>
                          <td>
                            CPU {row.capacity?.cpu || "未提供"}
                            <div className="muted">
                              内存 {row.capacity?.memory || "未提供"}
                            </div>
                          </td>
                        </>
                      )}
                      {kind === "files" && (
                        <>
                          <td className="file-path">
                            <button
                              className="link mono"
                              onClick={() => onSource(row.path!)}
                            >
                              {row.path}
                            </button>
                          </td>
                          <td>
                            <Pill>{row.category}</Pill>
                          </td>
                          <td>{bytes(row.size || 0)}</td>
                          <td>
                            <button
                              className="link"
                              onClick={() => onSource(row.path!)}
                            >
                              查看
                            </button>
                          </td>
                        </>
                      )}
                      {kind === "events" && (
                        <>
                          <td>
                            <Pill
                              tone={row.type === "Warning" ? "warn" : "blue"}
                            >
                              {row.type || "未知"}
                            </Pill>
                            <div>{row.reason}</div>
                          </td>
                          <td>
                            {row.objectKind} / {row.objectName}
                            <div className="muted">
                              {row.namespace || "集群对象"}
                            </div>
                          </td>
                          <td>
                            {row.time || "未提供"}
                            <div className="muted">次数 {value(row.count)}</div>
                          </td>
                          <td className="event-message">
                            {row.message}
                            <div className="muted">{row.association}</div>
                            <Source path={row.source} onOpen={onSource} />
                          </td>
                        </>
                      )}
                      {kind === "resources" &&
                        resourceColumns.map((c) => (
                          <td key={c}>{value(row[c])}</td>
                        ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!loading && !data?.items.length && (
              <Empty>
                {kind === "resources" &&
                overview.resources.find((r) => r.name === resource)?.state ===
                  "empty"
                  ? "采集时未发现该类资源"
                  : "没有符合条件的记录；缺失数据不代表健康。"}
              </Empty>
            )}
            <Pagination
              data={data}
              cursor={query.cursor}
              onCursor={(cursor) => nav.set({ cursor })}
            />
          </Panel>
        </div>
      </div>
    </>
  );
}
