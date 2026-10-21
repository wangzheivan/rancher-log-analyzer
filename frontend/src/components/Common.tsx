import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
  FileText,
} from "lucide-react";
import { useCatalog } from "../hooks";
import type { Item, PageData } from "../model";
export const scopes: Record<string, string> = {
  system: "系统/平台",
  business: "业务",
  unknown: "未分类",
};
export const statuses: Record<string, string> = {
  ok: "已采集",
  empty: "空文件/有效空",
  failed: "采集命令失败",
  missing: "当前包未发现",
  partial: "部分可用",
  unsupported: "不支持的格式",
  unknown: "无法判断",
  na: "不适用",
};
export function Pill({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Panel({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Message({
  error,
  loading,
}: {
  error?: string;
  loading?: boolean;
}) {
  return error ? (
    <div className="note warning" role="alert">
      {error}
    </div>
  ) : loading ? (
    <div className="loading-line">正在读取…</div>
  ) : null;
}
export function Source({
  path,
  onOpen,
}: {
  path?: string;
  onOpen: (path: string) => void;
}) {
  return path ? (
    <button className="link" onClick={() => onOpen(path)}>
      <FileText size={13} />
      查看原文
    </button>
  ) : null;
}
export function SearchBox({
  value,
  onChange,
  label = "搜索",
  placeholder = "搜索…",
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  placeholder?: string;
}) {
  return (
    <div className="search-field">
      <Search size={16} />
      <input
        aria-label={label}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
export function Pagination({
  data,
  cursor = "",
  onCursor,
}: {
  data: PageData | null;
  cursor?: string;
  onCursor: (cursor: string) => void;
}) {
  const [history, setHistory] = useState<string[]>([]);
  useEffect(() => {
    if (!cursor) setHistory([]);
  }, [cursor]);
  return (
    <div className="pager">
      <span>共 {data?.total ?? "—"} 条 · 服务端分页</span>
      <div>
        <button
          className="ghost"
          disabled={!cursor}
          onClick={() => {
            const next =
              data?.previousCursor || history[history.length - 1] || "";
            setHistory(history.slice(0, -1));
            onCursor(next);
          }}
        >
          <ChevronLeft size={14} />
          上一页
        </button>
        <button
          className="ghost"
          disabled={!data?.nextCursor}
          onClick={() => {
            setHistory([...history, cursor]);
            onCursor(data!.nextCursor!);
          }}
        >
          下一页
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
export function AsyncSelect({
  bundle,
  kind,
  value,
  label,
  onChange,
  filters = {},
  nameValue = false,
  selectedLabel = "",
}: {
  bundle: string;
  kind: string;
  value: string;
  label: string;
  onChange: (value: string, item?: Item) => void;
  filters?: Record<string, string | boolean>;
  nameValue?: boolean;
  selectedLabel?: string;
}) {
  const [q, setQ] = useState(""),
    [open, setOpen] = useState(false),
    [cursor, setCursor] = useState(""),
    [picked, setPicked] = useState<{ id: string; label: string } | null>(null);
  const { data, error, loading } = useCatalog(bundle, kind, {
    ...filters,
    q,
    cursor,
    limit: 50,
  });
  const getKey = (row: Item) => (nameValue ? row.name : row.id);
  const current =
    picked?.id === value
      ? picked.label
      : data?.items.find((r) => getKey(r) === value)?.name ||
        selectedLabel ||
        (nameValue || kind === "namespaces" || kind === "components"
          ? value
          : "");
  return (
    <div
      className="async-select"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <label>{label}</label>
      <div className="async-control">
        <input
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          aria-controls={"options-" + label}
          aria-autocomplete="list"
          value={open ? q : current || ""}
          placeholder={`搜索${label}…`}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQ(e.target.value);
            setCursor("");
            setOpen(true);
          }}
        />
        <button
          className="icon-button"
          aria-label={`清除${label}`}
          onClick={() => {
            onChange("");
            setPicked(null);
            setQ("");
            setCursor("");
          }}
        >
          <X size={12} />
        </button>
        <button
          className="icon-button"
          aria-label={`展开${label}`}
          onClick={() => setOpen(!open)}
        >
          <ChevronDown size={13} />
        </button>
      </div>
      {open && (
        <div
          className="async-options"
          id={"options-" + label}
          role="listbox"
          aria-label={`${label}候选项`}
        >
          <Message error={error} loading={loading} />
          {data?.items.map((row) => (
            <button
              role="option"
              aria-selected={value === getKey(row)}
              key={row.id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                const key = getKey(row);
                setPicked({ id: key, label: row.name });
                onChange(key, row);
                setQ("");
                setOpen(false);
              }}
            >
              <span>
                {row.name}
                <small>
                  {row.namespace}
                  {row.uid ? ` · UID ${row.uid.slice(0, 8)}` : ""}
                </small>
              </span>
              {row.logCount !== undefined && <Pill>{row.logCount} 文件</Pill>}
            </button>
          ))}
          {!loading && !data?.items.length && (
            <div className="source-line">没有候选项</div>
          )}
          <div className="async-page">
            <span>共 {data?.total ?? 0} 项</span>
            <button
              className="link"
              onMouseDown={(e) => e.preventDefault()}
              disabled={!cursor}
              onClick={() => setCursor("")}
            >
              首页
            </button>
            <button
              className="link"
              onMouseDown={(e) => e.preventDefault()}
              disabled={!data?.nextCursor}
              onClick={() => setCursor(data!.nextCursor!)}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
export function value(input: unknown): string {
  if (input === undefined || input === null || input === "") return "未提供";
  return typeof input === "object" ? JSON.stringify(input) : String(input);
}
