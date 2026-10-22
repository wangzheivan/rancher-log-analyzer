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
  PodStatus,
  SearchBox,
  Source,
  statuses,
  value,
} from "../components/Common";
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
}: PageProps & { kind: "pods" }) {
  const p = nav.params;
  const filter = (v: Record<string, string>) =>
    nav.set({ ...v, cursor: "" }, true);
  const query = {
    q: p.get("q") || "",
    namespace: p.get("namespace") || "",
    node: p.get("node") || "",
    status: p.get("status") || "",
    cursor: p.get("cursor") || "",
    limit: 50,
  };
  const { data, error, loading } = useCatalog(bundle, "pods", query);
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
          label="搜索 Pod"
          placeholder="搜索 Pod 名称、命名空间或 IP…"
          value={query.q}
          onChange={(q) => filter({ q })}
        />
        <AsyncSelect
          bundle={bundle}
          kind="namespaces"
          label="命名空间"
          value={query.namespace}
          onChange={(namespace) => filter({ namespace })}
        />
        <AsyncSelect
          bundle={bundle}
          kind="nodes"
          nameValue
          label="节点"
          value={query.node}
          onChange={(node) => filter({ node })}
        />
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
      </div>
      <Panel
        title="Pod 清单"
        action={
          <Source
            path={overview.resources.find((r) => r.name === "pods")?.source}
            onOpen={onSource}
          />
        }
      >
        <Message error={error} loading={loading} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "Pod / 命名空间",
                  "就绪 / 状态",
                  "节点",
                  "重启 / AGE",
                  "采集日志",
                ].map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.items.map((row) => (
                <tr key={row.id}>
                  <td>
                    <button
                      className="link entity-link"
                      onClick={() => nav.go("pod-detail", { id: row.id }, true)}
                    >
                      {row.name}
                    </button>
                    <div className="muted">{row.namespace}</div>
                  </td>
                  <td>
                    <span className="mono">{row.ready}</span>
                    <br />
                    <PodStatus status={row.status} attention={row.attention} />
                  </td>
                  <td>{row.node || "未提供"}</td>
                  <td>
                    {value(row.RESTARTS)}
                    <div className="muted">{value(row.AGE)}</div>
                  </td>
                  <td>
                    {row.logCount ? (
                      <>
                        <button className="link" onClick={() => log(row)}>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!loading && !data?.items.length && (
          <Empty>没有符合条件的 Pod；缺失数据不代表健康。</Empty>
        )}
        <Pagination
          data={data}
          cursor={query.cursor}
          onCursor={(cursor) => nav.set({ cursor })}
        />
      </Panel>
    </>
  );
}
