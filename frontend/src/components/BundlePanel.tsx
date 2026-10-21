import { useEffect, useState } from "react";
import type { BundleRecord } from "../types";
import { bytes, stateNames } from "../api";
import { Empty, Panel, Pill } from "./Common";
export function BundlePanel({
  caseId,
  bundles,
  selected,
  onSelect,
  onDelete,
  onClose,
}: {
  caseId: string;
  bundles: BundleRecord[];
  selected: string;
  onSelect: (id: string) => void;
  onDelete: (b: BundleRecord) => void;
  onClose: () => void;
}) {
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [caseId]);
  useEffect(() => {
    if (page * 10 >= bundles.length)
      setPage(Math.max(0, Math.ceil(bundles.length / 10) - 1));
  }, [bundles.length, page]);
  return (
    <Panel
      title={`案例内采集包 · ${bundles.length} 份`}
      action={
        <button className="link" onClick={onClose}>
          收起
        </button>
      }
    >
      <div className="bundle-list">
        {bundles.slice(page * 10, page * 10 + 10).map((b) => (
          <div
            className={`bundle-row ${b.id === selected ? "selected" : ""}`}
            key={b.id}
          >
            <button className="link bundle-name" onClick={() => onSelect(b.id)}>
              <strong>{b.name}</strong>
              <small>
                {b.hostname || "等待解析"} · {b.generated || "未提供采集时间"} ·{" "}
                {b.distro?.toUpperCase() || "等待识别"}
              </small>
            </button>
            <Pill
              tone={
                b.state === "ready"
                  ? "good"
                  : b.state === "failed"
                    ? "warn"
                    : "blue"
              }
            >
              {stateNames[b.state] || b.state}
            </Pill>
            <span className="muted">解压 {bytes(b.unpackedBytes)}</span>
            {b.id === selected && <Pill tone="blue">当前展示</Pill>}
            <span className="bundle-error">{b.error}</span>
            <button className="link danger" onClick={() => onDelete(b)}>
              {["ready", "failed"].includes(b.state) ? "删除" : "取消导入"}
            </button>
          </div>
        ))}
      </div>
      {!bundles.length && <Empty>尚未上传采集包</Empty>}
      {bundles.length > 10 && (
        <div className="pager">
          <span>
            共 {bundles.length} 份 · 第 {page + 1} 页
          </span>
          <div>
            <button
              className="ghost"
              disabled={!page}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </button>
            <button
              className="ghost"
              disabled={(page + 1) * 10 >= bundles.length}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </Panel>
  );
}
