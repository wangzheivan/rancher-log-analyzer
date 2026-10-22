import { useApi, useDebounced } from "../hooks";
import type { Item, PageData } from "../model";
import type { PageProps } from "./Browse";
import {
  Empty,
  Message,
  Panel,
  Pagination,
  Pill,
  SearchBox,
  Source,
} from "../components/Common";
const states: Record<string, string> = {
  valid: "有效",
  expiring: "90 天内到期",
  expired: "已过期",
  notYetValid: "尚未生效",
  unknown: "无法判断",
};
const purposes: Record<string, string> = {
  ca: "CA 证书",
  client: "客户端证书",
  server: "服务端证书",
  other: "其他证书",
};
const tones: Record<string, string> = {
  valid: "good",
  expiring: "warn",
  expired: "bad",
  notYetValid: "warn",
  unknown: "",
};
interface Certificate extends Item {
  validity: string;
  purpose: string;
  sourceIndex: number;
  node: string;
  subject?: string;
  issuer?: string;
  notBefore?: string;
  notAfter?: string;
  isCA?: boolean;
  san?: string;
  remainingDays?: number | null;
  parseState: string;
}
interface CertificatePage extends PageData<Certificate> {
  counts: Record<string, number>;
  checkedAt: string;
  referenceTime: string | null;
  referenceMessage: string;
  collectedTime: string;
}
function date(value?: string | null) {
  return value
    ? new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC")
    : "未提供";
}
export function CertificatesPage({ bundle, nav, onSource }: PageProps) {
  const p = nav.params;
  const q = useDebounced(p.get("q") || ""),
    zone = useDebounced(p.get("zone") || "");
  const basis = p.get("basis") || "current";
  const query = new URLSearchParams({
    q,
    basis,
    zone: basis === "collected" ? zone : "",
    status: p.get("status") || "",
    purpose: p.get("purpose") || "",
    cursor: p.get("cursor") || "",
    refresh: p.get("refresh") || "",
  });
  const { data, error, loading } = useApi<CertificatePage>(
    `/bundles/${bundle}/certificates?${query}`,
  );
  function filter(values: Record<string, string>) {
    nav.set({ cursor: "", ...values }, true);
  }
  return (
    <>
      <div className="note">
        仅检查采集到的证书有效期，不代表在线集群仍使用该证书。本页不验证证书链、吊销或密钥匹配；所有时间以
        UTC 展示。
      </div>
      <div className="toolbar certificate-filters">
        <label>
          检查时间
          <select
            aria-label="证书检查时间"
            value={basis}
            onChange={(e) => filter({ basis: e.target.value })}
          >
            <option value="current">当前时间</option>
            <option value="collected">采集时刻</option>
          </select>
        </label>
        {basis === "collected" && (
          <label>
            采集时区（歧义时必填）
            <input
              aria-label="采集时区"
              placeholder="如 Asia/Shanghai"
              value={p.get("zone") || ""}
              onChange={(e) => filter({ zone: e.target.value })}
            />
          </label>
        )}
        <label>
          状态
          <select
            aria-label="证书状态"
            value={p.get("status") || ""}
            onChange={(e) => filter({ status: e.target.value })}
          >
            <option value="">全部状态</option>
            {Object.entries(states).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          用途
          <select
            aria-label="证书用途"
            value={p.get("purpose") || ""}
            onChange={(e) => filter({ purpose: e.target.value })}
          >
            <option value="">全部用途</option>
            {Object.entries(purposes).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <SearchBox
          label="搜索证书"
          placeholder="按证书名称、Subject、Issuer 或路径搜索…"
          value={p.get("q") || ""}
          onChange={(q) => filter({ q })}
        />
      </div>
      <Message error={error} loading={loading} />
      {data && (
        <>
          <div className="note" role="status">
            {data.referenceMessage} · 判断时间：{date(data.referenceTime)}
            <br />
            采集时间原文：{data.collectedTime} · 请求检查时刻：
            {date(data.checkedAt)}
            {basis === "current" && (
              <button
                className="link"
                onClick={() => filter({ refresh: String(Date.now()) })}
              >
                刷新检查
              </button>
            )}
          </div>
          <div className="certificate-counts">
            {Object.entries(states).map(([key, label]) => (
              <button
                className={`certificate-count ${p.get("status") === key ? "selected" : ""}`}
                key={key}
                onClick={() =>
                  filter({ status: p.get("status") === key ? "" : key })
                }
              >
                <Pill tone={tones[key]}>{label}</Pill>
                <strong>{data.counts[key] || 0}</strong>
              </button>
            ))}
          </div>
          <Panel title="采集证书">
            {!data.items.length ? (
              <Empty>
                当前筛选下未发现证书记录；缺失不代表证书有效。首版仅解析 certs
                目录内的 OpenSSL 证书文本。
              </Empty>
            ) : (
              <div className="certificate-list">
                {data.items.map((cert) => (
                  <article className="certificate-card" key={cert.id}>
                    <div className="certificate-heading">
                      <div>
                        <strong>{cert.name}</strong>
                        <span className="muted">
                          {" "}
                          · {cert.node} · 文件内第 {cert.sourceIndex} 份
                        </span>
                      </div>
                      <Pill tone={tones[cert.validity]}>
                        {states[cert.validity]}
                      </Pill>
                    </div>
                    <dl className="certificate-meta">
                      <dt>用途</dt>
                      <dd>
                        {purposes[cert.purpose]} · CA：
                        {cert.parseState === "ok"
                          ? cert.isCA
                            ? "是"
                            : "否"
                          : "无法判断"}
                      </dd>
                      <dt>生效时间</dt>
                      <dd>{date(cert.notBefore)}</dd>
                      <dt>到期时间</dt>
                      <dd>{date(cert.notAfter)}</dd>
                      <dt>剩余时间</dt>
                      <dd>
                        {cert.remainingDays == null
                          ? "无法判断"
                          : cert.remainingDays < 0
                            ? `已过期（剩余 ${cert.remainingDays} 天，向下取整）`
                            : `${cert.remainingDays} 天（向下取整）`}
                      </dd>
                      <dt>Subject</dt>
                      <dd>{cert.subject || "未提供"}</dd>
                      <dt>Issuer</dt>
                      <dd>{cert.issuer || "未提供"}</dd>
                      <dt>SAN</dt>
                      <dd>{cert.san || "未提供"}</dd>
                      <dt>来源</dt>
                      <dd>
                        {cert.path}{" "}
                        <Source path={cert.source} onOpen={onSource} />
                      </dd>
                    </dl>
                    {cert.note && (
                      <div className="note warning">{cert.note}</div>
                    )}
                  </article>
                ))}
              </div>
            )}
            <Pagination
              data={data}
              cursor={p.get("cursor") || ""}
              onCursor={(cursor) => nav.set({ cursor })}
            />
          </Panel>
        </>
      )}
    </>
  );
}
