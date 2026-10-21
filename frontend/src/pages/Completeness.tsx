import type { PageProps } from "./Browse";
import type { Coverage } from "../model";
import { useApi } from "../hooks";
import { Message, Panel, Pill, Source, statuses } from "../components/Common";
export function CompletenessPage({ bundle, onSource }: PageProps) {
  const { data, error, loading } = useApi<Coverage>(
    `/bundles/${bundle}/completeness`,
  );
  return (
    <>
      <div className="note">
        只展示采集证据与可用性，不推断集群健康。“未发现”不能证明采集器尝试过采集；“不适用”和“采集失败”需要明确证据。
      </div>
      <Message error={error} loading={loading} />
      {data && (
        <>
          <div className="summary-banner">
            <strong>
              快照 Pod 日志覆盖：{data.podsWithLogs} / {data.podCount}
            </strong>
            <span>日志中存在但快照已消失的 Pod，可在独立日志页检索。</span>
          </div>
          {data.groups.map((group) => (
            <Panel
              key={group.id}
              title={group.name}
              action={
                <>
                  <Pill
                    tone={
                      group.state === "ok"
                        ? "good"
                        : group.state === "failed" || group.state === "partial"
                          ? "warn"
                          : ""
                    }
                  >
                    {group.label}
                  </Pill>
                  <span className="muted">{group.count} 个文件</span>
                </>
              }
            >
              <div className="panel-body">
                <div className="coverage-counts">
                  {Object.entries(group.counts).map(([state, count]) => (
                    <span key={state}>
                      {statuses[state] || state}：{count}
                    </span>
                  ))}
                </div>
                {group.evidence && (
                  <pre className="evidence">{group.evidence}</pre>
                )}
                <details>
                  <summary>来源文件与证据预览 · 最多50个</summary>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>路径</th>
                          <th>状态 / 说明</th>
                          <th>原文</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.files.map((f) => (
                          <tr key={f.id}>
                            <td className="file-path mono">{f.path}</td>
                            <td>
                              {statuses[f.state] || f.state}
                              <div className="muted">{f.note}</div>
                            </td>
                            <td>
                              <Source path={f.path} onOpen={onSource} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
                <p className="muted">{group.note}</p>
              </div>
            </Panel>
          ))}
          {data.warnings.map((w) => (
            <div className="note warning" key={w}>
              {w}
            </div>
          ))}
        </>
      )}
    </>
  );
}
