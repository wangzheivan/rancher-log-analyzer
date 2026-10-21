import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { bytes } from "../api";
import { useApi } from "../hooks";
import type { FilePage, Item } from "../model";
import { Message } from "./Common";
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const result = [];
  let start = 0,
    at = 0;
  const lower = text.toLowerCase(),
    needle = query.toLowerCase();
  while ((at = lower.indexOf(needle, start)) >= 0) {
    result.push(
      text.slice(start, at),
      <mark key={at}>{text.slice(at, at + query.length)}</mark>,
    );
    start = at + query.length;
  }
  result.push(text.slice(start));
  return <>{result}</>;
}
export function LogReader({
  bundle,
  fileId,
  tail = true,
  offset = 0,
}: {
  bundle: string;
  fileId: string;
  tail?: boolean;
  offset?: number;
}) {
  const [draft, setDraft] = useState(""),
    [query, setQuery] = useState(""),
    [window, setWindow] = useState({
      direction: tail ? "backward" : "forward",
      anchor: tail ? "end" : offset ? "" : "start",
      offset,
      end: "",
    });
  useEffect(() => {
    setQuery("");
    setDraft("");
    setWindow({
      direction: tail ? "backward" : "forward",
      anchor: tail ? "end" : offset ? "" : "start",
      offset,
      end: "",
    });
  }, [fileId, tail, offset]);
  const { data: file } = useApi<Item>(
    `/bundles/${bundle}/files/${fileId}/info`,
  );
  const qs = new URLSearchParams({
    q: query,
    direction: window.direction,
    anchor: window.anchor,
    offset: String(window.offset),
  });
  if (window.end) qs.set("end", window.end);
  const { data, error, loading } = useApi<FilePage>(
    `/bundles/${bundle}/files/${fileId}?${qs}`,
  );
  function jump(end: boolean) {
    setWindow({
      direction: end ? "backward" : "forward",
      anchor: end ? "end" : "start",
      offset: 0,
      end: "",
    });
  }
  return (
    <div className="log-reader">
      <div className="log-file-heading">
        <span className="mono">{file?.path || "正在定位文件…"}</span>
        <span>{bytes(file?.size || 0)}</span>
      </div>
      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(draft);
          jump(tail);
        }}
      >
        <div className="search-field">
          <Search size={15} />
          <input
            aria-label="日志关键字"
            maxLength={500}
            placeholder="搜索当前文件（不区分大小写）"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <button className="primary" disabled={loading}>
          搜索
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            setDraft("");
            setQuery("");
            jump(tail);
          }}
        >
          重置
        </button>
        <button type="button" className="ghost" onClick={() => jump(false)}>
          开头
        </button>
        <button type="button" className="ghost" onClick={() => jump(true)}>
          末尾
        </button>
      </form>
      <Message error={error} />
      <div className="reader-note">
        按需读取，单次扫描最多 2 MiB / 展示最多 250
        条；实例号代表采集文件中的实例，不等于实时容器状态。
      </div>
      <pre className="reader-content" aria-label="文件内容" tabIndex={0}>
        {loading
          ? "正在读取…"
          : data?.binary
            ? data.message
            : data?.lines.length
              ? data.lines.map((line, i) => (
                  <span className="log-line" key={i}>
                    <span className="log-offset">
                      {data.segments[i].offset}
                    </span>
                    <span>
                      <Highlight text={line} query={query} />
                      {data.segments[i].continued && (
                        <span className="segment-label"> [长行分段 →]</span>
                      )}
                    </span>
                  </span>
                ))
              : query
                ? "本次扫描未找到匹配内容；有可用游标时可继续向前或向后搜索。"
                : "文件为空。"}
      </pre>
      <div className="viewer-bottom">
        <span>
          {data
            ? `${data.lines.length} 条 · 本次扫描 ${bytes(data.scannedBytes)} · 文件 ${bytes(data.size)}`
            : "读取中…"}
        </span>
        <div className="table-actions">
          <button
            className="ghost"
            disabled={loading || data?.beforeCursor == null}
            onClick={() =>
              setWindow({
                direction: "backward",
                anchor: "",
                offset: 0,
                end: String(data!.beforeCursor),
              })
            }
          >
            {query ? "向前搜索" : "向前读取"}
          </button>
          <button
            className="primary"
            disabled={loading || data?.afterCursor == null}
            onClick={() =>
              setWindow({
                direction: "forward",
                anchor: "",
                offset: data!.afterCursor!,
                end: "",
              })
            }
          >
            {query ? "向后搜索" : "向后读取"}
          </button>
        </div>
      </div>
    </div>
  );
}
export function SourceDialog({
  bundle,
  fileId,
  offset = 0,
  onClose,
}: {
  bundle: string;
  fileId: string;
  offset?: number;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} className="source-dialog" onCancel={onClose}>
      <div className="viewer-head">
        <h2>原始采集文件</h2>
        <button className="ghost" aria-label="关闭文件" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <LogReader bundle={bundle} fileId={fileId} tail={false} offset={offset} />
    </dialog>
  );
}
