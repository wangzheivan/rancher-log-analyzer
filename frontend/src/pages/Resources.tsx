import type { PageProps } from "./Browse";
import { useCatalog } from "../hooks";
import {
  AsyncSelect,
  Empty,
  Message,
  Pagination,
  Panel,
  SearchBox,
  Source,
  value,
} from "../components/Common";
export function ResourcesPage({ bundle, nav, overview, onSource }: PageProps) {
  const p = nav.params;
  const resource =
    p.get("resource") ||
    overview.resources.find((r) => r.name === "deployments")?.name ||
    overview.resources[0]?.name ||
    "";
  const q = p.get("q") || "",
    cursor = p.get("cursor") || "";
  const types = useCatalog(bundle, "resources", {
    q: p.get("typeQ") || "",
    cursor: p.get("typeCursor") || "",
    limit: 50,
  });
  const rows = useCatalog(bundle, "resources", {
    resource,
    q,
    cursor,
    namespace: p.get("namespace") || "",
    limit: 50,
  });
  return (
    <div className="resource-layout">
      <section className="panel resource-menu">
        <div className="resource-type-search">
          <SearchBox
            label="搜索资源类型"
            placeholder="搜索资源类型…"
            value={p.get("typeQ") || ""}
            onChange={(typeQ) => nav.set({ typeQ, typeCursor: "" }, true)}
          />
        </div>
        <Message error={types.error} loading={types.loading} />
        {types.data?.items.map((r) => (
          <button
            key={r.name}
            className={r.name === resource ? "active" : ""}
            onClick={() =>
              nav.set(
                { resource: r.name, q: "", namespace: "", cursor: "" },
                true,
              )
            }
          >
            <span>{r.name}</span>
            <small>{String(r.count)}</small>
          </button>
        ))}
        <Pagination
          data={types.data}
          cursor={p.get("typeCursor") || ""}
          onCursor={(typeCursor) => nav.set({ typeCursor })}
        />
      </section>
      <div className="resource-content">
        <div className="toolbar">
          <SearchBox
            label="搜索资源"
            placeholder="筛选当前资源表的可见列…"
            value={q}
            onChange={(q) => nav.set({ q, cursor: "" }, true)}
          />
          <AsyncSelect
            bundle={bundle}
            kind="namespaces"
            label="命名空间"
            value={p.get("namespace") || ""}
            onChange={(namespace) => nav.set({ namespace, cursor: "" }, true)}
          />
        </div>
        <Panel
          title={resource || "资源快照"}
          action={<Source path={rows.data?.source} onOpen={onSource} />}
        >
          <Message error={rows.error} loading={rows.loading} />
          {rows.data?.note && (
            <div className="note warning">{rows.data.note}</div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {rows.data?.columns?.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.data?.items.map((r, i) => (
                  <tr key={r.id || i}>
                    {rows.data?.columns?.map((c) => (
                      <td key={c}>{value(r[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!rows.loading && !rows.data?.items.length && (
            <Empty>
              {rows.data?.state === "empty"
                ? "采集时未发现该类资源"
                : rows.data?.state === "failed"
                  ? "采集命令失败，请查看原文"
                  : rows.data?.state === "unknown"
                    ? "无法解析此采集表格，请查看原文"
                    : "没有符合条件的资源"}
            </Empty>
          )}
          <Pagination
            data={rows.data}
            cursor={cursor}
            onCursor={(cursor) => nav.set({ cursor })}
          />
          <div className="source-line">
            来源：{rows.data?.source || "未提供"}
          </div>
        </Panel>
      </div>
    </div>
  );
}
