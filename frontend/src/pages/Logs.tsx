import { useEffect } from "react";
import type { PageProps } from "./Browse";
import { useCatalog } from "../hooks";
import {
  AsyncSelect,
  Empty,
  Message,
  Panel,
  Pagination,
  Pill,
  SearchBox,
  scopes,
  componentGroups,
  statuses,
} from "../components/Common";
import { LogReader } from "../components/LogReader";
export function LogsPage({
  bundle,
  nav,
  componentMode = false,
}: PageProps & { componentMode?: boolean }) {
  const p = nav.params;
  const pod = p.get("pod") || "",
    file = p.get("file") || "",
    all = p.get("all") === "1";
  const query = {
    namespace: p.get("namespace") || "",
    pod: componentMode ? "" : pod,
    node: p.get("node") || "",
    scope: componentMode ? "" : p.get("scope") || "",
    component_group: componentMode ? p.get("componentGroup") || "" : "",
    component: p.get("component") || "",
    q: p.get("q") || "",
    cursor: p.get("cursor") || "",
  };
  const { data, error, loading } = useCatalog(
    componentMode || pod ? bundle : "",
    componentMode ? "componentLogs" : "logs",
    query,
  );
  useEffect(() => {
    if (!file && data?.items.length) {
      const choices = [...data.items].sort(
        (a, b) =>
          (a.variant === "current" ? -1 : 0) -
            (b.variant === "current" ? -1 : 0) ||
          (b.instance ?? -1) - (a.instance ?? -1),
      );
      nav.set({ file: choices[0].id }, true);
    }
  }, [data, file]);
  const chosen = data?.items.find((l) => l.id === file);
  function filter(values: Record<string, string>) {
    nav.set({ file: "", cursor: "", ...values }, true);
  }
  return (
    <>
      <div className="log-filters toolbar">
        {!componentMode && (
          <>
            <AsyncSelect
              bundle={bundle}
              kind="namespaces"
              label="命名空间"
              value={query.namespace}
              onChange={(namespace) =>
                filter({ namespace, pod: "", podName: "" })
              }
            />
            <AsyncSelect
              bundle={bundle}
              kind={all ? "pods" : "logPods"}
              label="Pod"
              value={pod}
              selectedLabel={p.get("podName") || ""}
              filters={{
                namespace: query.namespace,
                scope: all ? "" : query.scope,
              }}
              onChange={(selected, row) => {
                if (all && row) {
                  filter({
                    pod: row.logPodId || "",
                    podName: row.name,
                    file: row.logFileId || "",
                    empty: row.logCount ? "" : "1",
                  });
                } else
                  filter({
                    pod: selected,
                    podName: row?.name || "",
                    file: row?.logFileId || "",
                    empty: "",
                  });
              }}
            />
            <button
              className="ghost"
              onClick={() =>
                filter({ pod: "unassociated", podName: "未关联日志" })
              }
            >
              未关联日志
            </button>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={all}
                onChange={(e) =>
                  filter({
                    all: e.target.checked ? "1" : "",
                    pod: "",
                    podName: "",
                    empty: "",
                  })
                }
              />
              包含无日志 Pod
            </label>
            <select
              aria-label="日志分类"
              value={query.scope}
              onChange={(e) =>
                filter({ scope: e.target.value, pod: "", podName: "" })
              }
            >
              <option value="">全部分类</option>
              {Object.entries(scopes).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </>
        )}
        {componentMode && (
          <>
            <label>
              日志分组
              <select
                aria-label="组件分组"
                value={query.component_group}
                onChange={(e) =>
                  filter({ componentGroup: e.target.value, component: "" })
                }
              >
                <option value="">全部分组</option>
                {Object.entries(componentGroups).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <AsyncSelect
              bundle={bundle}
              kind="nodes"
              label="节点"
              nameValue
              value={query.node}
              onChange={(node) => filter({ node, component: "" })}
            />
            <AsyncSelect
              bundle={bundle}
              kind="components"
              label="组件"
              filters={{
                component_group: query.component_group,
                node: query.node,
              }}
              value={query.component}
              onChange={(component) => filter({ component })}
            />
            <SearchBox
              label="搜索组件日志"
              placeholder="按组件、文件或Pod名称搜索…"
              value={query.q}
              onChange={(q) => filter({ q })}
            />
          </>
        )}
      </div>
      <div className="note">
        {componentMode
          ? "按明确的组件及主机服务来源组织。监控等其他平台 Pod 请在 Pod 日志中查看；核心组件 Pod 可从两个入口打开同一源文件。"
          : "默认展示有采集日志的 Pod，包含已从快照消失的对象。文件中的实例号和 Pod UID 会保留，避免把旧实例误当成当前实例。"}
      </div>
      {!componentMode && !pod ? (
        <Empty>
          {p.get("empty") === "1"
            ? "当前采集包未发现所选 Pod 的日志。"
            : "请选择命名空间或搜索 Pod，打开该 Pod 的采集日志。"}
        </Empty>
      ) : (
        <div className="log-layout">
          <Panel title={componentMode ? "组件与系统日志文件" : "日志文件"}>
            <Message error={error} loading={loading} />
            <div className="log-sources">
              {data?.items.map((log) => (
                <button
                  className={`log-source ${file === log.id ? "active" : ""}`}
                  key={log.id}
                  onClick={() => nav.set({ file: log.id }, true)}
                >
                  <strong>
                    {componentMode
                      ? log.component || log.name
                      : log.pod || log.name}
                  </strong>
                  {log.namespace && (
                    <span className="log-namespace">{log.namespace}</span>
                  )}
                  <span>
                    {log.container || (log.pod ? "未区分容器" : "服务日志")}
                  </span>
                  <span>
                    {log.instance !== undefined && log.instance >= 0
                      ? `采集实例 ${log.instance}${log.rotation || ""}`
                      : log.variant === "previous"
                        ? "上一次日志"
                        : log.variant === "current"
                          ? `当前日志${log.rotation || ""}`
                          : "采集源文件"}
                  </span>
                  {componentMode && (
                    <span>
                      {componentGroups[log.componentGroup || ""]} ·{" "}
                      {log.sourceType === "journald"
                        ? "journald"
                        : log.sourceType === "pod"
                          ? "Pod 日志"
                          : "文件日志"}
                    </span>
                  )}
                  <small>{log.path}</small>
                  <div>
                    <Pill
                      tone={
                        log.status === "failed"
                          ? "warn"
                          : log.status === "ok"
                            ? "good"
                            : ""
                      }
                    >
                      {log.status === "empty" && log.note === "有效无记录"
                        ? "有效无记录"
                        : statuses[log.status || ""]}
                    </Pill>
                    <Pill>{scopes[log.scope || "unknown"]}</Pill>
                  </div>
                </button>
              ))}
            </div>
            {!loading && !data?.items.length && (
              <Empty>当前筛选下没有日志文件</Empty>
            )}
            <Pagination
              data={data}
              cursor={query.cursor}
              onCursor={(cursor) => nav.set({ cursor })}
            />
          </Panel>
          <div className="log-main">
            {file ? (
              <>
                <div className="note compact-note">
                  {componentMode
                    ? chosen?.componentReason || "采集源文件"
                    : chosen?.basis || "采集源文件"}
                  {chosen?.classificationReason
                    ? ` · 分类依据：${chosen.classificationReason}`
                    : ""}
                  {chosen?.pod && !chosen.container && (
                    <div>
                      采集器将该 Pod
                      的所有容器日志输出到同一文件，未提供可靠的容器标识，无法拆分。
                    </div>
                  )}
                  {componentMode && chosen?.podId && (
                    <button
                      className="link"
                      onClick={() =>
                        nav.go(
                          "pod-logs",
                          {
                            pod: chosen.podId || "",
                            podName: chosen.pod || "",
                            namespace: chosen.namespace || "",
                            file: chosen.id,
                          },
                          true,
                        )
                      }
                    >
                      在 Pod 日志中查看 →
                    </button>
                  )}
                  {chosen?.uid ? ` · UID：${chosen.uid}` : ""}
                  {chosen?.note && <div>{chosen.note}</div>}
                </div>
                <LogReader key={file} bundle={bundle} fileId={file} />
              </>
            ) : (
              <Empty>
                在左侧选择容器、实例或日志源文件。默认从末尾读取最多250条。
              </Empty>
            )}
          </div>
        </div>
      )}
    </>
  );
}
