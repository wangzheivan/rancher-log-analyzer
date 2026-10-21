import { useApi, useCatalog } from "../hooks";
import type { Detail } from "../model";
import type { PageProps } from "./Browse";
import {
  Empty,
  Message,
  Pagination,
  Panel,
  Pill,
  Source,
  value,
} from "../components/Common";
function object(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" && !Array.isArray(input)
    ? (input as Record<string, unknown>)
    : {};
}
function array(input: unknown): Record<string, unknown>[] {
  return Array.isArray(input) ? input.map(object) : [];
}
function Fields({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="meta detail-meta">
      {Object.entries(data).map(([key, item]) => (
        <div className="meta-pair" key={key}>
          <dt>{key}</dt>
          <dd>{value(item)}</dd>
        </div>
      ))}
    </dl>
  );
}
export function DetailPage({ bundle, nav, onSource, overview }: PageProps) {
  const kind = nav.params.get("page") === "node-detail" ? "nodes" : "pods",
    id = nav.params.get("id") || "";
  const { data, error, loading } = useApi<Detail>(
    id ? `/bundles/${bundle}/detail/${kind}/${id}` : null,
  );
  const row = data?.summary,
    meta = object(data?.object?.metadata),
    spec = object(data?.object?.spec),
    status = object(data?.object?.status);
  const {
    data: events,
    error: eventError,
    loading: eventLoading,
  } = useCatalog(row ? bundle : "", "events", {
    object_name: row?.name || "",
    object_kind: kind === "nodes" ? "Node" : "Pod",
    object_uid: row?.uid || "",
    namespace: kind === "pods" ? row?.namespace || "" : "",
    limit: 10,
    cursor: nav.params.get("eventCursor") || "",
  });
  const {
    data: pods,
    error: podError,
    loading: podLoading,
  } = useCatalog(kind === "nodes" && row ? bundle : "", "pods", {
    node: row?.name || "",
    cursor: nav.params.get("relatedCursor") || "",
    limit: 50,
  });
  const { data: matching } = useCatalog(
    row && kind === "pods" ? bundle : "",
    "pods",
    { namespace: row?.namespace || "", name: row?.name || "", limit: 1 },
  );
  const pod = matching?.items[0];
  return (
    <>
      <button className="ghost back-button" onClick={nav.back}>
        ← 返回并恢复列表
      </button>
      <Message error={error} loading={loading} />
      {data && row && (
        <>
          <div className="summary-banner">
            <div>
              <strong>
                {kind === "pods" ? "Pod" : "Node"} / {row.name}
              </strong>
              <p>
                {row.namespace || "集群级对象"}{" "}
                {row.uid ? `· UID ${row.uid}` : ""}
              </p>
            </div>
            <div className="table-actions">
              <Source path={row.source} onOpen={onSource} />
              {kind === "pods" && pod?.logCount ? (
                <button
                  className="primary"
                  onClick={() =>
                    nav.go(
                      "pod-logs",
                      {
                        namespace: row.namespace || "",
                        pod: pod.logPodId || "",
                        podName: row.name,
                        file: pod.logFileId || "",
                      },
                      true,
                    )
                  }
                >
                  查看采集日志
                </button>
              ) : null}
            </div>
          </div>
          <div className="grid">
            <Panel title="基本信息">
              <div className="panel-body">
                <Fields
                  data={
                    kind === "pods"
                      ? {
                          命名空间: row.namespace,
                          节点: row.node,
                          状态: row.status,
                          就绪: row.ready,
                          重启次数: row.restartCount,
                          IP: row.IP,
                          创建时间: meta.creationTimestamp,
                          调度: spec.nodeName,
                        }
                      : {
                          角色: row.roles,
                          IP: row.ip,
                          Kubelet: row.kubeletVersion,
                          操作系统: row.osImage,
                          内核: row.kernelVersion,
                          运行时: row.containerRuntimeVersion,
                          容量: row.capacity,
                          可分配: row.allocatable,
                        }
                  }
                />
              </div>
            </Panel>
            <Panel
              title={kind === "pods" ? "调度与快照状态" : "节点 Conditions"}
            >
              <div className="panel-body">
                {kind === "nodes" ? (
                  row.conditions?.length ? (
                    row.conditions.map((c) => (
                      <div className="condition-detail" key={c.type}>
                        <Pill>
                          {c.type}: {c.status}
                        </Pill>
                        <p>{c.reason}</p>
                        <small>{c.message}</small>
                      </div>
                    ))
                  ) : (
                    <Empty>未提供节点 Conditions</Empty>
                  )
                ) : (
                  <Fields
                    data={{
                      调度器: spec.schedulerName,
                      "Node Selector": spec.nodeSelector,
                      Tolerations: spec.tolerations,
                      Conditions: status.conditions,
                      QoS: status.qosClass,
                    }}
                  />
                )}
              </div>
            </Panel>
          </div>
          {kind === "pods" && (
            <Panel title="容器与 Init Container">
              <div className="panel-body">
                {data.object ? (
                  [
                    "initContainers",
                    "containers",
                    "ephemeralContainers",
                  ].flatMap((type) =>
                    array(spec[type]).map((container) => {
                      const name = String(container.name);
                      const states = array(
                        status[
                          type === "initContainers"
                            ? "initContainerStatuses"
                            : type === "ephemeralContainers"
                              ? "ephemeralContainerStatuses"
                              : "containerStatuses"
                        ],
                      );
                      const state = states.find((c) => c.name === name) || {};
                      return (
                        <div className="container-card" key={type + "/" + name}>
                          <h3>
                            {name} <Pill>{type}</Pill>
                          </h3>
                          <Fields
                            data={{
                              镜像: container.image,
                              命令: container.command,
                              参数: container.args,
                              状态: state.state,
                              上次状态: state.lastState,
                              重启次数: state.restartCount,
                              "资源请求/限制": container.resources,
                              Liveness: container.livenessProbe,
                              Readiness: container.readinessProbe,
                              Startup: container.startupProbe,
                              挂载: container.volumeMounts,
                            }}
                          />
                        </div>
                      );
                    }),
                  )
                ) : data.describe?.containers.length ? (
                  data.describe.containers.map((c) => (
                    <div className="container-card" key={c.type + "/" + c.name}>
                      <h3>
                        {c.name} <Pill>{c.type}</Pill>
                      </h3>
                      <Fields
                        data={{
                          ...c.fields,
                          "资源请求/限制": c.resources,
                          挂载: c.mounts,
                        }}
                      />
                    </div>
                  ))
                ) : (
                  <Empty>
                    当前来源未提供容器详情，请查看原文或补充采集数据。
                  </Empty>
                )}
              </div>
            </Panel>
          )}
          {data.describe && (
            <Panel
              title="Describe 补充信息"
              action={
                <button
                  className="link"
                  onClick={() =>
                    onSource(data.describe!.source, data.describe!.offset)
                  }
                >
                  查看此对象原文
                </button>
              }
            >
              <div className="panel-body">
                <Fields data={data.describe.fields} />
                {[
                  "Labels",
                  "Annotations",
                  "Volumes",
                  "Capacity",
                  "Allocatable",
                  "Addresses",
                  "System Info",
                  "Taints",
                  "Node-Selectors",
                  "Tolerations",
                  "Allocated resources",
                  "Non-terminated Pods",
                  "Conditions",
                ].map((key) =>
                  data.describe?.sections[key] ? (
                    <details key={key}>
                      <summary>{key}</summary>
                      <pre className="compact-pre">
                        {data.describe.sections[key]}
                      </pre>
                    </details>
                  ) : null,
                )}
                {data.describe.truncated && (
                  <div className="note warning">
                    此对象详情超过1 MiB预览预算，完整信息请查看原文。
                  </div>
                )}
              </div>
            </Panel>
          )}
          {!data.object && !data.describe && (
            <div className="note">
              当前包只提供了列表信息，未发现可关联的详细来源。
            </div>
          )}
          <Panel title="关联事件">
            <Message error={eventError} loading={eventLoading} />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>类型 / 原因</th>
                    <th>时间</th>
                    <th>消息</th>
                    <th>关联依据</th>
                  </tr>
                </thead>
                <tbody>
                  {events?.items.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <Pill tone={e.type === "Warning" ? "warn" : "blue"}>
                          {e.type}
                        </Pill>
                        <div>{e.reason}</div>
                      </td>
                      <td>{e.time || "未提供"}</td>
                      <td className="event-message">
                        {e.message}
                        <br />
                        <Source path={e.source} onOpen={onSource} />
                      </td>
                      <td>{e.association}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              data={events}
              cursor={nav.params.get("eventCursor") || ""}
              onCursor={(eventCursor) => nav.set({ eventCursor })}
            />
            {!eventLoading && !events?.items.length && (
              <Empty>
                当前采集数据未提供可关联事件；这不代表对象没有发生过异常。
              </Empty>
            )}
          </Panel>
          {kind === "nodes" && (
            <Panel title="关联 Pod · 服务端分页">
              <Message error={podError} loading={podLoading} />
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Pod</th>
                      <th>命名空间</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pods?.items.map((p) => (
                      <tr key={p.id}>
                        <td>
                          <button
                            className="link"
                            onClick={() =>
                              nav.go("pod-detail", { id: p.id }, true)
                            }
                          >
                            {p.name}
                          </button>
                        </td>
                        <td>{p.namespace}</td>
                        <td>{p.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                data={pods}
                cursor={nav.params.get("relatedCursor") || ""}
                onCursor={(relatedCursor) => nav.set({ relatedCursor })}
              />
            </Panel>
          )}
          {data.object && (
            <Panel title="结构化来源补充">
              <div className="panel-body">
                <details>
                  <summary>Labels / Annotations / Volumes</summary>
                  <Fields
                    data={{
                      Labels: meta.labels,
                      Annotations: meta.annotations,
                      Volumes: spec.volumes,
                    }}
                  />
                </details>
              </div>
            </Panel>
          )}
        </>
      )}
      {!id && <Empty>未选择对象</Empty>}
    </>
  );
}
