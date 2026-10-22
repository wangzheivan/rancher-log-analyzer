import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  LayoutDashboard,
  Server,
  Boxes,
  FileText,
  Terminal,
  Layers,
  ClipboardCheck,
  ShieldCheck,
  HardDrive,
  Upload,
  Plus,
  Pencil,
  Trash2,
} from "lucide-react";
import { API, api, bytes, jsonBody, stateNames } from "./api";
import { useApi, useLocation } from "./hooks";
import type { Case, Session, BundleRecord } from "./types";
import type { Item, Overview } from "./model";
import { Empty, Message, Pill } from "./components/Common";
import { SourceDialog } from "./components/LogReader";
import { BrowsePage } from "./pages/Browse";
import { OverviewPage, SystemPage } from "./pages/Overview";
import { LogsPage } from "./pages/Logs";
import { DetailPage } from "./pages/Detail";
import { NodesPage } from "./pages/Nodes";
import { ResourcesPage } from "./pages/Resources";
import { FilesPage } from "./pages/Files";
import { BundlePanel } from "./components/BundlePanel";
import { CertificatesPage } from "./pages/Certificates";
import { CompletenessPage } from "./pages/Completeness";
const pages = [
  ["overview", "采集概览", LayoutDashboard],
  ["nodes", "集群节点", Server],
  ["pods", "Pod 工作负载", Boxes],
  ["pod-logs", "Pod 日志", Terminal],
  ["components", "组件与系统日志", Layers],
  ["certificates", "证书检查", ShieldCheck],
  ["resources", "资源快照", FileText],
  ["system", "主机与 etcd", HardDrive],
  ["completeness", "采集完整性", ClipboardCheck],
  ["files", "原始文件", FileText],
] as const;
const active = ["uploading", "queued", "extracting", "indexing", "parsing"];
export function App() {
  const nav = useLocation(),
    p = nav.params,
    caseId = p.get("case") || "",
    bundleId = p.get("bundle") || "",
    page = p.get("page") || "overview";
  const [manage, setManage] = useState(false),
    [packagesClosed, setPackagesClosed] = useState(false);
  useEffect(() => {
    if (page === "events") nav.go("resources", { resource: "events" });
  }, [page]);
  useEffect(() => {
    setManage(false);
    setPackagesClosed(false);
  }, [caseId]);
  const sourceRequest = useRef<AbortController | null>(null);
  const [cases, setCases] = useState<Case[]>([]),
    [session, setSession] = useState<Session | null>(null),
    [loaded, setLoaded] = useState(false),
    [error, setError] = useState(""),
    [upload, setUpload] = useState<{ name: string; progress: number } | null>(
      null,
    ),
    [viewer, setViewer] = useState<{ id: string; offset: number } | null>(null),
    [modal, setModal] = useState<"create" | "rename" | null>(null),
    [name, setName] = useState(""),
    [saving, setSaving] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    fileInput = useRef<HTMLInputElement>(null),
    xhr = useRef<XMLHttpRequest | null>(null);
  const current = cases.find((c) => c.id === caseId),
    bundles = current?.bundles || [],
    bundle = bundles.find((b) => b.id === bundleId);
  const refresh = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api<Case[]>("/cases"),
        api<Session>("/session"),
      ]);
      setCases(c);
      setSession(s);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
      setLoaded(true);
    }
  }, []);
  const processing = cases.some((c) =>
    c.bundles.some((b) => active.includes(b.state)),
  );
  useEffect(() => {
    void refresh();
    const timer = setInterval(
      () => void refresh(),
      processing || upload ? 1500 : 15000,
    );
    return () => clearInterval(timer);
  }, [refresh, processing, !!upload]);
  useEffect(() => {
    if (!loaded) return;
    if (!current) {
      nav.selectScope({
        case: cases[0]?.id || "",
        bundle: cases[0]?.bundles[0]?.id || "",
      });
    } else if (!bundle) {
      nav.selectScope({ bundle: bundles[0]?.id || "" });
    }
  }, [cases, caseId, bundleId, loaded]);
  useEffect(() => {
    if (modal) dialog.current?.showModal();
  }, [modal]);
  useEffect(() => {
    setViewer(null);
    sourceRequest.current?.abort();
    return () => sourceRequest.current?.abort();
  }, [bundleId]);
  const { data: overview, error: overviewError } = useApi<Overview>(
    bundle?.state === "ready" ? `/bundles/${bundleId}/overview` : null,
  );
  async function source(path: string, offset = 0) {
    sourceRequest.current?.abort();
    const controller = new AbortController();
    sourceRequest.current = controller;
    try {
      const f = await api<Item>(
        `/bundles/${bundleId}/file-source?path=${encodeURIComponent(path)}`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted) setViewer({ id: f.id, offset });
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const c = await api<Case>(
        modal === "rename" ? `/cases/${caseId}` : "/cases",
        {
          method: modal === "rename" ? "PATCH" : "POST",
          ...jsonBody({ name }),
        },
      );
      await refresh();
      if (modal !== "rename") nav.selectScope({ case: c.id, bundle: "" });
      setModal(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function removeCase() {
    if (!current || !confirm(`删除案例“${current.name}”及其全部采集数据？`))
      return;
    try {
      await api(`/cases/${caseId}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function removeBundle(b: BundleRecord) {
    if (!confirm(`删除采集包“${b.name}”？`)) return;
    try {
      await api(`/bundles/${b.id}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function send(files: FileList | null) {
    if (!files || !caseId) return;
    const target = caseId;
    setError("");
    try {
      for (const file of Array.from(files)) {
        if (!/\.(tar\.gz|tgz)$/i.test(file.name))
          throw Error(`文件“${file.name}”不支持，仅支持 .tar.gz 或 .tgz`);
        if (session && file.size > session.maxUploadBytes)
          throw Error("压缩包大小超过限制");
        setUpload({ name: file.name, progress: 0 });
        await new Promise<void>((resolve, reject) => {
          const request = new XMLHttpRequest();
          xhr.current = request;
          request.open(
            "POST",
            `${API}/cases/${target}/bundles?filename=${encodeURIComponent(file.name)}`,
          );
          request.setRequestHeader("Content-Type", "application/gzip");
          request.upload.onprogress = (e) => {
            if (e.lengthComputable)
              setUpload({
                name: file.name,
                progress: Math.round((e.loaded / e.total) * 100),
              });
          };
          request.onload = () => {
            if (request.status >= 200 && request.status < 300) resolve();
            else {
              try {
                reject(Error(JSON.parse(request.responseText).detail));
              } catch {
                reject(Error(`上传失败 ${request.status}`));
              }
            }
          };
          request.onerror = () => reject(Error("上传连接失败"));
          request.onabort = () => reject(Error("上传已取消"));
          request.send(file);
        });
        await refresh();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUpload(null);
      xhr.current = null;
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  const props = overview
    ? { bundle: bundleId, nav, overview, onSource: source }
    : null;
  const title =
    page === "pod-detail"
      ? "Pod 详情"
      : page === "node-detail"
        ? "Node 详情"
        : pages.find((x) => x[0] === page)?.[1] || "采集概览";
  return (
    <>
      <aside>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            nav.go("overview");
          }}
        >
          <span className="brand-icon">
            <Activity size={26} />
          </span>
          <div>
            RANCHER<span>SUPPORT EXPLORER</span>
          </div>
        </a>
        <div className="workspace-label">离线排障工作台</div>
        <nav aria-label="主导航">
          {pages.map(([id, label, Icon]) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => nav.go(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          共享临时工作区
          <br />
          服务重启会清空所有数据
        </div>
      </aside>
      <div className="workspace">
        <header className="app-header">
          <span>Rancher 日志可视化</span>
          <Pill tone="blue">离线采集快照</Pill>
        </header>
        <main>
          <div className="workspace-notice">
            所有访问者共享案例，可查看和删除数据。服务重启后数据清空，请保留原始采集包。
          </div>
          <div className="workspace-controls">
            <label>
              案例
              <select
                aria-label="选择案例"
                value={caseId}
                onChange={(e) =>
                  nav.selectScope({ case: e.target.value, bundle: "" })
                }
              >
                <option value="">选择案例</option>
                {cases.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary new-case-button"
              onClick={() => {
                setName("");
                setModal("create");
              }}
            >
              <Plus size={15} />
              新建案例
            </button>
            <button
              className="icon-button"
              aria-label="重命名案例"
              disabled={!current}
              onClick={() => {
                setName(current!.name);
                setModal("rename");
              }}
            >
              <Pencil size={15} />
            </button>
            <button
              className="icon-button"
              aria-label="删除案例"
              disabled={!current || !!upload}
              onClick={() => void removeCase()}
            >
              <Trash2 size={15} />
            </button>
            <label className="bundle-select">
              采集包
              <select
                aria-label="选择采集包"
                value={bundleId}
                onChange={(e) => nav.selectScope({ bundle: e.target.value })}
              >
                <option value="">选择采集包</option>
                {bundles.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.hostname || b.name} · {stateNames[b.state] || b.state}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary"
              disabled={!current || !!upload}
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={15} />
              上传采集包
            </button>
            <input
              hidden
              ref={fileInput}
              type="file"
              multiple
              aria-describedby="upload-format-hint"
              aria-label="上传采集包文件"
              onChange={(e) => void send(e.target.files)}
            />
          </div>
          <p id="upload-format-hint" className="upload-format-hint">
            支持 .tar.gz / .tgz，请选择未解压的原始采集包。
          </p>
          {current && (
            <div className="package-toggle">
              <button
                className="ghost"
                onClick={() => {
                  if (page === "overview") setPackagesClosed(!packagesClosed);
                  else setManage(!manage);
                }}
              >
                管理采集包 · {bundles.length} 份
              </button>
            </div>
          )}
          {current && (page === "overview" ? !packagesClosed : manage) && (
            <BundlePanel
              caseId={caseId}
              bundles={bundles}
              selected={bundleId}
              onSelect={(bundle) => nav.selectScope({ bundle })}
              onDelete={(b) => void removeBundle(b)}
              onClose={() => {
                setManage(false);
                setPackagesClosed(true);
              }}
            />
          )}
          {upload && (
            <div className="note">
              上传 {upload.name} · {upload.progress}%{" "}
              <progress value={upload.progress} max={100} />
              <button className="link" onClick={() => xhr.current?.abort()}>
                取消上传
              </button>
            </div>
          )}
          <Message error={error || overviewError} />
          {error && (
            <button className="link" onClick={() => setError("")}>
              关闭提示
            </button>
          )}
          <div className="page-heading">
            <div>
              <h1>{title}</h1>
              <p>{bundle?.hostname || "采集数据"} · 各采集包独立展示</p>
            </div>
            {session && (
              <span className="muted">
                会话 {bytes(session.usedBytes)} /{" "}
                {bytes(session.maxSessionBytes)}
              </span>
            )}
          </div>
          {!bundle ? (
            <Empty>
              {loaded
                ? "创建案例并上传 Rancher 官方采集包，即可浏览采集信息。"
                : "正在加载工作区…"}
            </Empty>
          ) : bundle.state !== "ready" ? (
            <div className="panel panel-body">
              <h2>{stateNames[bundle.state] || bundle.state}</h2>
              <p>{bundle.error || "正在串行解压并建立临时元数据索引。"}</p>
              <button
                className="ghost"
                onClick={() => void removeBundle(bundle)}
              >
                删除/取消采集包
              </button>
            </div>
          ) : props ? (
            <>
              {page === "overview" && <OverviewPage {...props} />}
              {(["pods"] as const).map(
                (kind) =>
                  page === kind && (
                    <BrowsePage key={kind} kind={kind} {...props} />
                  ),
              )}
              {page === "nodes" && <NodesPage {...props} />}
              {page === "resources" && <ResourcesPage {...props} />}
              {page === "files" && <FilesPage {...props} />}
              {page === "pod-logs" && <LogsPage {...props} />}
              {page === "components" && <LogsPage {...props} componentMode />}
              {page === "certificates" && <CertificatesPage {...props} />}
              {page === "system" && <SystemPage {...props} />}
              {(page === "pod-detail" || page === "node-detail") && (
                <DetailPage {...props} />
              )}
              {page === "completeness" && <CompletenessPage {...props} />}
              <div className="bundle-actions">
                <span className="muted">{bundle.name}</span>
                <button
                  className="link danger"
                  onClick={() => void removeBundle(bundle)}
                >
                  删除此采集包
                </button>
              </div>
            </>
          ) : (
            <Empty>正在读取概览…</Empty>
          )}
        </main>
      </div>
      {viewer && (
        <SourceDialog
          key={bundleId + viewer.id}
          bundle={bundleId}
          fileId={viewer.id}
          offset={viewer.offset}
          onClose={() => setViewer(null)}
        />
      )}
      {modal && (
        <dialog
          className="case-dialog"
          ref={dialog}
          onCancel={() => setModal(null)}
        >
          <form onSubmit={save}>
            <h2>{modal === "create" ? "创建案例" : "重命名案例"}</h2>
            <label>
              案例名称
              <input
                aria-label="案例名称"
                autoFocus
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <p>用于组织多个采集节点的数据。</p>
            <div className="table-actions">
              <button
                type="button"
                className="ghost"
                onClick={() => setModal(null)}
              >
                取消
              </button>
              <button className="primary" disabled={saving}>
                保存
              </button>
            </div>
          </form>
        </dialog>
      )}
    </>
  );
}
