import { useEffect, useState, useRef } from "react";
import { api, bytes, jsonBody } from "../api";
import { useApi, useDebounced } from "../hooks";
import type { Item, PageData } from "../model";
import type { PageProps } from "./Browse";
import {
  AsyncSelect,
  Empty,
  Message,
  Pagination,
  Panel,
  Pill,
  SearchBox,
  Source,
} from "../components/Common";
const severityNames: Record<string, string> = {
  high: "高风险",
  warning: "需关注",
  info: "提示",
  unknown: "无法判断",
};
const tones: Record<string, string> = {
  high: "bad",
  warning: "warn",
  info: "blue",
  unknown: "",
};
const stateNames: Record<string, string> = {
  queued: "排队中",
  running: "分析中",
  complete: "已完成所选范围",
  partial: "达到本轮扫描预算",
  cancelled: "已取消",
  failed: "分析未完成",
  blocked: "分析未运行",
};
const tabs: Record<string, string> = {
  snapshot: "快照与配置发现",
  history: "日志中的历史信号",
  unknown: "未能完成的检查",
};
interface Finding extends Item {
  ruleId: string;
  category: string;
  severity: string;
  evidenceType: string;
  title: string;
  observed: string;
  observedTruncated?: boolean;
  condition: string;
  advice: string;
  docs?: string;
  count: number;
  eventPreview?: Item[];
  eventsTotal?: number;
  object: {
    kind: string;
    id: string;
    entityId?: string;
    name: string;
    namespace?: string;
    node?: string;
    source?: string;
    uid?: string;
    podId?: string;
    snapshotPodId?: string;
    logFileId?: string;
  };
}
interface Status {
  state: string;
  phase?: string;
  error: string;
  runId: string;
  ruleVersion: string;
  checkedAt: string;
  counts: Record<string, number>;
  checks: Record<string, number>;
  categories: Record<string, string>;
  thresholds: Record<string, number[]>;
  coverage: {
    candidateFiles?: number;
    visitedFiles?: number;
    completeFiles?: number;
    candidateBytes?: number;
    remainingBytes?: number;
    scannedBytes?: number;
    roundBytes?: number;
    roundFiles?: number;
    structuredComplete?: boolean;
    candidateListComplete?: boolean;
  };
  limits?: {
    roundBytes: number;
    roundFiles: number;
    fileBytes: number;
    resultBytes: number;
  };
  canContinue: boolean;
  resultBytes: number;
  facts?: {
    id: string;
    label: string;
    value: string;
    source: string;
    note: string;
  }[];
  checkCoverage?: Record<string, Record<string, number>>;
  observations?: {
    rule: string;
    name: string;
    value: number;
    source: string;
    measurements: number;
    note: string;
  }[];
}
interface Evidence extends Item {
  fileId: string;
  offset: number;
  text: string;
  rawTime: string;
  parsedTime: string;
  path: string;
}
interface Detail extends Finding {
  evidence: PageData<Evidence>;
  events?: PageData;
  eventPreview?: Item[];
}
function useStatus(bundle: string) {
  const path = `/bundles/${bundle}/analysis`;
  const [result, setResult] = useState<{ path: string; data: Status } | null>(
      null,
    ),
    [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await api<Status>(path, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setResult({ path, data });
          setError("");
          timer = setTimeout(
            poll,
            ["queued", "running"].includes(data.state) ? 1500 : 15000,
          );
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError((e as Error).message);
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, refresh]);
  return {
    data: result?.path === path ? result.data : null,
    error,
    refresh: () => setRefresh((v) => v + 1),
  };
}
export function AnalysisPage({ bundle, nav, onSource }: PageProps) {
  const p = nav.params;
  const { data: status, error, refresh } = useStatus(bundle);
  const [actionError, setActionError] = useState(""),
    [busy, setBusy] = useState(false),
    [expanded, setExpanded] = useState(false);
  const tab = p.get("evidence_type") || "snapshot",
    selected = p.get("finding") || "";
  const detailRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected)
      detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selected]);
  const previousRun = useRef("");
  useEffect(() => {
    if (status?.runId) {
      if (previousRun.current && previousRun.current !== status.runId)
        nav.set(
          { cursor: "", finding: "", eventCursor: "", evidenceCursor: "" },
          true,
        );
      previousRun.current = status.runId;
    }
  }, [status?.runId]);
  const q = useDebounced(p.get("q") || "");
  const revision = `${status?.runId || ""}:${status?.coverage.scannedBytes || 0}:${Object.values(status?.counts || {}).reduce((a, b) => a + b, 0)}:${status?.state || ""}`;
  const query = new URLSearchParams({
    limit: "50",
    cursor: p.get("cursor") || "",
    q,
    category: p.get("category") || "",
    severity: p.get("severity") || "",
    namespace: p.get("namespace") || "",
    node: p.get("node") || "",
    evidence_type: tab,
    revision,
  });
  const {
    data: list,
    error: listError,
    loading,
  } = useApi<PageData<Finding>>(
    `/bundles/${bundle}/analysis/findings?${query}`,
  );
  const {
    data: detail,
    error: detailError,
    loading: detailLoading,
  } = useApi<Detail>(
    selected
      ? `/bundles/${bundle}/analysis/findings/${selected}?${new URLSearchParams({ cursor: p.get("evidenceCursor") || "", event_cursor: p.get("eventCursor") || "", revision })}`
      : null,
  );
  useEffect(() => setExpanded(false), [selected, bundle]);
  function filter(values: Record<string, string>) {
    nav.set(
      {
        cursor: "",
        finding: "",
        eventCursor: "",
        evidenceCursor: "",
        ...values,
      },
      true,
    );
  }
  async function action(action: string) {
    setBusy(true);
    setActionError("");
    try {
      await api(`/bundles/${bundle}/analysis`, {
        method: "POST",
        ...jsonBody({ action }),
      });
      refresh();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function objectLink(row: Finding) {
    const obj = row.object;
    const id = obj.entityId || obj.snapshotPodId;
    if (obj.kind === "Pod" && id) nav.go("pod-detail", { id }, true);
    else if (obj.kind === "Node" && id) nav.go("node-detail", { id }, true);
    else if (obj.kind === "Certificate")
      nav.go("certificates", { q: obj.name }, true);
  }
  const running = status && ["queued", "running"].includes(status.state);
  return (
    <>
      <div className="note">
        离线采集证据初筛，不是实时健康检查或根因结论。快照发现与历史日志分开展示；未扫描、缺失及无法解析的数据不会判为正常。
      </div>
      <Message error={error || actionError} />
      {status && (
        <>
          <div className="analysis-summary summary-banner">
            <div>
              <strong>{stateNames[status.state] || status.state}</strong>
              <p>
                规则 {status.ruleVersion || "—"} · 分析时刻{" "}
                {status.checkedAt || "—"}
              </p>
              <small>
                结构化检查：
                {status.coverage.structuredComplete
                  ? "已完成"
                  : "未完成"} · {status.checks?.passed || 0}{" "}
                项检查在采集证据中通过，不代表整体健康
              </small>
            </div>
            <div className="table-actions">
              <button
                className="ghost"
                disabled={busy || !status.canContinue || !!running}
                onClick={() => void action("continue")}
              >
                继续扫描
              </button>
              <button
                className="ghost"
                disabled={busy || !running}
                onClick={() => void action("cancel")}
              >
                取消分析
              </button>
              <button
                className="ghost"
                disabled={busy || !!running}
                onClick={() => void action("restart")}
              >
                重新分析
              </button>
            </div>
          </div>
          {status.error && <div className="note warning">{status.error}</div>}
          <div className="certificate-counts analysis-counts">
            {Object.entries(severityNames).map(([key, label]) => (
              <button
                key={key}
                className="certificate-count"
                onClick={() =>
                  filter({
                    severity: p.get("severity") === key ? "" : key,
                    evidence_type:
                      key === "unknown"
                        ? "unknown"
                        : tab === "unknown"
                          ? "snapshot"
                          : tab,
                  })
                }
              >
                <Pill tone={tones[key]}>{label}</Pill>
                <strong>{status.counts[key] || 0}</strong>
              </button>
            ))}
          </div>
          <Panel title="检查与扫描覆盖">
            <div className="panel-body">
              <div className="analysis-coverage">
                <span>
                  候选目录：
                  {status.coverage.candidateListComplete
                    ? "已建立"
                    : "尚未完整建立"}
                </span>
                <span>
                  已访问 {status.coverage.visitedFiles || 0} /{" "}
                  {status.coverage.candidateFiles || 0} 个文件
                </span>
                <span>
                  完整扫描 {status.coverage.completeFiles || 0} 个文件
                </span>
                <span>
                  已扫描 {bytes(status.coverage.scannedBytes || 0)} /{" "}
                  {bytes(status.coverage.candidateBytes || 0)}
                </span>
                <span>
                  剩余 {bytes(status.coverage.remainingBytes || 0)}
                  ；未命中仅限已扫描范围
                </span>
              </div>
              <p className="muted">
                优先 etcd、核心与系统日志、异常 Pod 当前日志，最后
                previous；正常业务 Pod 日志不自动全量扫描。
                {status.limits && (
                  <>
                    每轮最多 {bytes(status.limits.roundBytes)} /{" "}
                    {status.limits.roundFiles} 文件，每文件窗口{" "}
                    {bytes(status.limits.fileBytes)}；结果预留{" "}
                    {bytes(status.limits.resultBytes)}（含回滚日志），当前数据库{" "}
                    {bytes(status.resultBytes)}。
                  </>
                )}
              </p>
              <details>
                <summary>结构化检查覆盖与适用性</summary>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>类别</th>
                        <th>证据通过</th>
                        <th>有发现</th>
                        <th>无法判断</th>
                        <th>不适用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(status.checkCoverage || {}).map(
                        ([key, c]) => (
                          <tr key={key}>
                            <td>{status.categories[key]}</td>
                            <td>{c.passed || 0}</td>
                            <td>{c.detected || 0}</td>
                            <td>{c.unknown || 0}</td>
                            <td>{c.na || 0}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </details>
              <details>
                <summary>
                  当前初筛阈值（项目配置，并非 Kubernetes 强制标准）
                </summary>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>关注阈值</th>
                        <th>高风险阈值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(status.thresholds || {}).map(
                        ([key, pair]) => (
                          <tr key={key}>
                            <td>{key}</td>
                            <td>
                              {key === "memoryAvailable" ? "<" : "≥"}
                              {pair[0]}
                            </td>
                            <td>
                              {key === "memoryAvailable" ? "<" : "≥"}
                              {pair[1]}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          </Panel>
          {!!status.facts?.length && (
            <Panel title="关键检查快照">
              <div className="analysis-observations">
                {status.facts.map((f) => (
                  <div key={f.id}>
                    <span>{f.label}</span>
                    <b>{f.value}</b>
                    <small>{f.note}</small>
                    <Source path={f.source} onOpen={onSource} />
                  </div>
                ))}
              </div>
            </Panel>
          )}
          {!!status.observations?.length && (
            <Panel title="采集节点资源快照">
              <div className="analysis-observations">
                {status.observations.map((m) => (
                  <div key={m.rule}>
                    <span>{m.name}</span>
                    <strong>{m.value.toFixed(2)}</strong>
                    <small>
                      {m.measurements > 1
                        ? `${m.measurements} 个文件系统取最大值 · `
                        : ""}
                      {m.note}
                    </small>
                    <Source path={m.source} onOpen={onSource} />
                  </div>
                ))}
              </div>
            </Panel>
          )}
          <div
            className="analysis-tabs"
            role="tablist"
            aria-label="发现证据类型"
          >
            {Object.entries(tabs).map(([key, label]) => (
              <button
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "active" : ""}
                key={key}
                onClick={() => filter({ evidence_type: key, severity: "" })}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="toolbar analysis-filters">
            <SearchBox
              label="搜索发现"
              placeholder="按对象、规则或异常信息搜索…"
              value={p.get("q") || ""}
              onChange={(q) => filter({ q })}
            />
            <label>
              类别
              <select
                aria-label="发现类别"
                value={p.get("category") || ""}
                onChange={(e) => filter({ category: e.target.value })}
              >
                <option value="">全部类别</option>
                {Object.entries(status.categories || {}).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              级别
              <select
                aria-label="发现级别"
                value={p.get("severity") || ""}
                onChange={(e) => filter({ severity: e.target.value })}
              >
                <option value="">全部级别</option>
                {Object.entries(severityNames).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <AsyncSelect
              bundle={bundle}
              kind="namespaces"
              label="发现命名空间"
              value={p.get("namespace") || ""}
              onChange={(namespace) => filter({ namespace })}
            />
            <AsyncSelect
              bundle={bundle}
              kind="nodes"
              label="发现节点"
              nameValue
              value={p.get("node") || ""}
              onChange={(node) => filter({ node })}
            />
          </div>
          <Message error={listError} loading={loading} />
          <Panel title={tabs[tab] || "发现列表"}>
            <div className="finding-list">
              {list?.items.map((row) => (
                <article
                  className={`finding-card ${row.severity}`}
                  key={row.id}
                >
                  <div className="finding-heading">
                    <strong>{row.title}</strong>
                    <Pill tone={tones[row.severity]}>
                      {severityNames[row.severity]}
                    </Pill>
                  </div>
                  <div className="muted">
                    {status.categories?.[row.category]} · {row.object.kind} /{" "}
                    {row.object.name}{" "}
                    {row.object.namespace ? `· ${row.object.namespace}` : ""}{" "}
                    {row.object.node ? `· ${row.object.node}` : ""}
                  </div>
                  <p>
                    {row.observed}
                    {row.observedTruncated && "（摘要已截断，请查看原文）"}
                  </p>
                  {row.eventPreview?.map((ev) => (
                    <div className="finding-event" key={ev.id}>
                      <Pill tone={ev.type === "Warning" ? "warn" : "blue"}>
                        {ev.reason}
                      </Pill>{" "}
                      {ev.message}
                      <small>
                        {" "}
                        · {ev.association} · {ev.time}
                      </small>
                    </div>
                  ))}
                  {row.eventsTotal !== undefined && (
                    <small>
                      关联事件 {row.eventsTotal}{" "}
                      条，预览最多3条；缺少事件不代表从未异常。
                    </small>
                  )}
                  <br />
                  <small>
                    {row.ruleId} ·{" "}
                    {row.evidenceType === "history"
                      ? `历史命中 ${row.count} 次，不代表当前故障`
                      : "采集证据检查"}
                  </small>
                  <div className="table-actions">
                    <button
                      className="link"
                      onClick={() =>
                        nav.set(
                          {
                            finding: row.id,
                            evidenceCursor: "",
                            eventCursor: "",
                          },
                          true,
                        )
                      }
                    >
                      查看证据与关联事件
                    </button>
                    {(row.object.entityId ||
                      row.object.snapshotPodId ||
                      row.object.kind === "Certificate") && (
                      <button className="link" onClick={() => objectLink(row)}>
                        查看对象 →
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {!loading && !list?.items.length && (
              <Empty>
                当前筛选下未发现对应记录；不代表未扫描或缺失的数据正常。
              </Empty>
            )}
            <Pagination
              data={list}
              cursor={p.get("cursor") || ""}
              onCursor={(cursor) => nav.set({ cursor, finding: "" })}
            />
          </Panel>
          {selected && (
            <div ref={detailRef}>
              <Panel
                title="发现证据与核查建议"
                action={
                  <button
                    className="ghost"
                    onClick={() => nav.set({ finding: "" }, true)}
                  >
                    收起证据
                  </button>
                }
              >
                <Message error={detailError} loading={detailLoading} />
                {detail && (
                  <div className="panel-body finding-detail">
                    <h3>{detail.title}</h3>
                    <p>{detail.condition}</p>
                    <div className="note">
                      {detail.advice}
                      {detail.docs && (
                        <>
                          {" "}
                          <a
                            href={detail.docs}
                            target="_blank"
                            rel="noreferrer"
                          >
                            官方资料 ↗
                          </a>
                        </>
                      )}
                    </div>
                    <div className="evidence-list">
                      {detail.evidence.items.map((ev) => (
                        <div key={ev.fileId + ":" + ev.offset}>
                          <div className="muted">
                            {ev.path || "结构化检查"} · 字节位置 {ev.offset}
                          </div>
                          {ev.rawTime && (
                            <div className="muted">
                              日志时间：{ev.parsedTime || ev.rawTime}
                              {!ev.parsedTime &&
                                "（保留原文，时区或格式不明确）"}
                            </div>
                          )}
                          <pre>{ev.text}</pre>
                          {ev.path && (
                            <Source
                              path={ev.path}
                              onOpen={(path) => onSource(path, ev.offset)}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                    <Pagination
                      data={detail.evidence}
                      cursor={p.get("evidenceCursor") || ""}
                      onCursor={(evidenceCursor) =>
                        nav.set({ evidenceCursor }, true)
                      }
                    />
                    {detail.events && (
                      <>
                        <h3>关联事件 · {detail.events.total} 条</h3>
                        {!detail.events.total && (
                          <p className="muted">
                            当前采集数据未提供关联事件，不代表没有发生异常。
                          </p>
                        )}
                        {(expanded
                          ? detail.events.items
                          : detail.eventPreview || []
                        ).map((ev) => (
                          <div className="finding-event" key={ev.id}>
                            <Pill
                              tone={ev.type === "Warning" ? "warn" : "blue"}
                            >
                              {ev.type}
                            </Pill>{" "}
                            {ev.reason} · {ev.time}
                            <p>{ev.message}</p>
                            <small>{ev.association}</small>{" "}
                            <Source path={ev.source} onOpen={onSource} />
                          </div>
                        ))}
                        {!expanded && detail.events.total > 3 && (
                          <button
                            className="link"
                            onClick={() => setExpanded(true)}
                          >
                            展开事件（每页10条）
                          </button>
                        )}
                        {expanded && (
                          <Pagination
                            data={detail.events}
                            cursor={p.get("eventCursor") || ""}
                            onCursor={(eventCursor) =>
                              nav.set({ eventCursor }, true)
                            }
                          />
                        )}
                      </>
                    )}
                  </div>
                )}
              </Panel>
            </div>
          )}
        </>
      )}
    </>
  );
}
