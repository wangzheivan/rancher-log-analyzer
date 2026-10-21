import { useEffect, useState } from "react";
import { api } from "./api";
import type { PageData, Item } from "./model";
export function useLocation() {
  const read = () => new URLSearchParams(window.location.hash.slice(1));
  const [params, setParams] = useState(read);
  useEffect(() => {
    const change = () => setParams(read());
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  function set(values: Record<string, string>, replace = false) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    write(next, replace);
  }
  function write(next: URLSearchParams, replace = false) {
    if (replace) {
      window.history.replaceState(null, "", "#" + next.toString());
      window.dispatchEvent(new Event("hashchange"));
    } else window.location.hash = next.toString();
  }
  function go(
    page: string,
    values: Record<string, string> = {},
    remember = false,
  ) {
    const next = new URLSearchParams();
    for (const key of ["case", "bundle"])
      if (params.get(key)) next.set(key, params.get(key)!);
    next.set("page", page);
    for (const [k, v] of Object.entries(values)) if (v) next.set(k, v);
    if (remember) next.set("back", params.toString());
    write(next);
  }
  function back() {
    const target = params.get("back");
    if (target) write(new URLSearchParams(target));
    else go("pods");
  }
  function selectScope(values: Record<string, string>) {
    const next = new URLSearchParams();
    for (const key of ["case", "bundle", "page"]) {
      const value = values[key] ?? params.get(key);
      if (value) next.set(key, value);
    }
    write(next);
  }
  return { params, set, go, back, selectScope };
}
export type Navigation = ReturnType<typeof useLocation>;
export function useDebounced<T>(value: T, delay = 250) {
  const [result, set] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => set(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return result;
}
export function useApi<T>(path: string | null) {
  const [result, setResult] = useState<{ path: string | null; data: T | null }>(
      { path: null, data: null },
    ),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    setResult({ path, data: null });
    setError("");
    if (!path) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    api<T>(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ path, data });
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path]);
  return { data: result.path === path ? result.data : null, error, loading };
}
export function useCatalog<T = Item>(
  bundle: string,
  kind: string,
  query: Record<string, string | boolean | number> = {},
) {
  const q = useDebounced(query.q ?? "");
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...query, q }))
    if (v !== "" && v !== false && v !== undefined) params.set(k, String(v));
  const search = params.toString();
  return useApi<PageData<T>>(
    bundle ? `/bundles/${bundle}/catalog/${kind}?${search}` : null,
  );
}
