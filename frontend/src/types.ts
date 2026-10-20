export interface BundleRecord {
  id: string;
  caseId: string;
  name: string;
  state: string;
  error: string;
  receivedBytes: number;
  unpackedBytes: number;
  hostname?: string;
  generated?: string;
  distro?: string;
}
export interface Case {
  id: string;
  name: string;
  createdAt: string;
  bundles: BundleRecord[];
}
export interface FileEntry {
  id: string;
  path: string;
  size: number;
  category: string;
}
export interface Node {
  name: string;
  roles: string;
  ip: string;
  ready: string;
  kubeletVersion?: string;
  osImage?: string;
  kernelVersion?: string;
  containerRuntimeVersion?: string;
  capacity: Record<string, string>;
  allocatable?: Record<string, string>;
  conditions: {
    type: string;
    status: string;
    reason?: string;
    message?: string;
  }[];
}
export interface Pod {
  NAMESPACE: string;
  NAME: string;
  READY: string;
  STATUS: string;
  RESTARTS: string;
  AGE: string;
  NODE: string;
  IP: string;
  restartCount: number;
  attention: boolean;
}
export interface Summary {
  name: string;
  hostname: string;
  generated: string;
  kernel: string;
  distro: string;
  os: string;
  version: string;
  files: FileEntry[];
  bytes: number;
  nodes: Node[];
  pods: Pod[];
  podStatus: Record<string, number>;
  namespaces: string[];
  resources: { name: string; count: number; source: string }[];
  system: Record<string, string>;
  etcd: Record<string, string>;
  warnings: string[];
}
export interface Resource {
  columns: string[];
  rows: Record<string, string>[];
  message?: string;
  skipped?: number;
  source: string;
}
export interface FilePage {
  path: string;
  binary: boolean;
  lines: string[];
  segments: { offset: number; continued: boolean }[];
  nextOffset: number;
  hasMore: boolean;
  size: number;
  scannedBytes: number;
}
export interface Session {
  usedBytes: number;
  maxSessionBytes: number;
  maxUploadBytes: number;
  maxUnpackBytes: number;
}
