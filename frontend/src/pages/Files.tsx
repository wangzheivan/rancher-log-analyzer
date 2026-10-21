import type { PageProps } from "./Browse";
import { useCatalog } from "../hooks";
import { bytes } from "../api";
import {
  Empty,
  Message,
  Pagination,
  Panel,
  Pill,
  SearchBox,
} from "../components/Common";
export function FilesPage({ bundle, nav, onSource }: PageProps) {
  const p = nav.params,
    group = p.get("group") || "",
    directory = p.get("directory") || "",
    q = p.get("q") || "",
    cursor = p.get("cursor") || "";
  const filter = (v: Record<string, string>) =>
    nav.set({ ...v, cursor: "" }, true);
  const groups = useCatalog(bundle, "fileGroups");
  const dirs = useCatalog(bundle, "fileDirectories", {
    group,
    directory,
    cursor: p.get("dirCursor") || "",
    limit: 50,
  });
  const files = useCatalog(bundle, "files", {
    group,
    directory,
    q,
    cursor,
    limit: 50,
  });
  const parts = directory.split("/").filter(Boolean);
  return (
    <>
      <div className="toolbar">
        <SearchBox
          label="搜索文件"
          placeholder="按文件名或路径筛选，例如 kubelet、podlogs、etcd…"
          value={q}
          onChange={(q) => filter({ q })}
        />
      </div>
      <Message error={groups.error} />
      <div className="category-strip" aria-label="文件用途分类">
        <button
          className={`chip ${!group ? "active" : ""}`}
          onClick={() => filter({ group: "", directory: "", dirCursor: "" })}
        >
          全部文件{" "}
          <span>
            {groups.data?.items.reduce(
              (sum, g) => sum + Number(g.count || 0),
              0,
            ) || 0}
          </span>
        </button>
        {groups.data?.items.map((g) => (
          <button
            key={g.id}
            className={`chip ${group === g.id ? "active" : ""}`}
            onClick={() =>
              filter({ group: g.id, directory: "", dirCursor: "" })
            }
          >
            <span>{g.name}</span>
            <span>
              {String(g.count)} · {bytes(Number(g.bytes || 0))}
            </span>
          </button>
        ))}
      </div>
      <div className="file-layout">
        <Panel title="原始目录">
          <Message error={dirs.error} loading={dirs.loading} />
          <div className="directory-menu">
            <button
              className={!directory ? "active" : ""}
              onClick={() => filter({ directory: "", dirCursor: "" })}
            >
              全部目录
            </button>
            {directory && (
              <button
                onClick={() =>
                  filter({
                    directory: parts.slice(0, -1).join("/"),
                    dirCursor: "",
                  })
                }
              >
                ← 上一级
              </button>
            )}
            {dirs.data?.items.map((d) => (
              <button
                key={d.id}
                onClick={() => filter({ directory: d.path!, dirCursor: "" })}
              >
                <strong>▸ {d.name}</strong>
                <small>
                  {String(d.count)} 文件 · {bytes(Number(d.bytes || 0))}
                </small>
              </button>
            ))}
            {!dirs.loading && !dirs.data?.items.length && (
              <div className="source-line">当前目录没有下级目录</div>
            )}
          </div>
          <Pagination
            data={dirs.data}
            cursor={p.get("dirCursor") || ""}
            onCursor={(dirCursor) => nav.set({ dirCursor })}
          />
        </Panel>
        <Panel
          title="原始文件"
          action={
            <span className="muted">
              {files.data?.total ?? 0} 文件 · {bytes(files.data?.bytes || 0)}
            </span>
          }
        >
          <div className="directory-breadcrumb">
            <button
              className="link"
              onClick={() => filter({ directory: "", dirCursor: "" })}
            >
              采集根目录
            </button>
            {parts.map((part, i) => (
              <span key={i}>
                {" "}
                /{" "}
                <button
                  className="link"
                  onClick={() =>
                    filter({
                      directory: parts.slice(0, i + 1).join("/"),
                      dirCursor: "",
                    })
                  }
                >
                  {part}
                </button>
              </span>
            ))}
          </div>
          <Message error={files.error} loading={files.loading} />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件路径</th>
                  <th>用途</th>
                  <th>大小</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {files.data?.items.map((f) => (
                  <tr key={f.id}>
                    <td className="file-path">
                      <button
                        className="link file-link mono"
                        onClick={() => onSource(f.path!)}
                      >
                        {f.path}
                      </button>
                    </td>
                    <td>
                      <Pill>{String(f.groupLabel || f.category)}</Pill>
                    </td>
                    <td>{bytes(f.size || 0)}</td>
                    <td>
                      <button
                        className="link"
                        onClick={() => onSource(f.path!)}
                      >
                        查看原文
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!files.loading && !files.data?.items.length && (
            <Empty>当前分类、目录和关键字下没有文件</Empty>
          )}
          <Pagination
            data={files.data}
            cursor={cursor}
            onCursor={(cursor) => nav.set({ cursor })}
          />
        </Panel>
      </div>
    </>
  );
}
