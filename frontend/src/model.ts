export interface Item {
  id: string;
  name: string;
  namespace?: string;
  uid?: string;
  node?: string;
  status?: string;
  path?: string;
  size?: number;
  category?: string;
  source?: string;
  note?: string;
  scope?: string;
  component?: string;
  classificationReason?: string;
  pod?: string;
  podId?: string;
  snapshotPodId?: string;
  container?: string;
  instance?: number;
  rotation?: string;
  variant?: string;
  basis?: string;
  logCount?: number;
  logState?: string;
  logPodId?: string;
  logFileId?: string;
  ready?: string;
  restartCount?: number;
  attention?: boolean;
  roles?: string;
  ip?: string;
  kubeletVersion?: string;
  osImage?: string;
  kernelVersion?: string;
  containerRuntimeVersion?: string;
  capacity?: Record<string, string>;
  allocatable?: Record<string, string>;
  conditions?: {
    type: string;
    status: string;
    reason?: string;
    message?: string;
  }[];
  objectKind?: string;
  objectName?: string;
  objectUid?: string;
  reason?: string;
  type?: string;
  message?: string;
  time?: string;
  count?: number | string;
  association?: string;
  [key: string]: unknown;
}
export interface PageData<T = Item> {
  items: T[];
  total: number;
  nextCursor: string | null;
  previousCursor?: string | null;
  source?: string;
}
export interface Overview {
  name: string;
  hostname: string;
  generated: string;
  kernel: string;
  distro: string;
  os: string;
  version: string;
  counts: Record<string, number>;
  bytes: number;
  podStatus: Record<string, number>;
  readyNodes: number;
  podLogCoverage: number;
  nodePreview: Item[];
  namespaceDistribution: { name: string; count: number }[];
  resources: {
    name: string;
    count: number;
    source: string;
    state: string;
    note: string;
  }[];
  warnings: string[];
  warningCount: number;
  system: Record<string, string>;
  etcd: Record<string, string>;
}
export interface Detail {
  summary: Item;
  object: Record<string, unknown> | null;
  describe: {
    fields: Record<string, string>;
    containers: {
      name: string;
      type: string;
      fields: Record<string, string>;
      resources: Record<string, Record<string, string>>;
      mounts: string[];
    }[];
    sections: Record<string, string>;
    source: string;
    fileId: string;
    offset: number;
    endOffset: number;
    truncated: boolean;
    raw: string;
  } | null;
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
  beforeCursor: number | null;
  afterCursor: number | null;
  message?: string;
  windowLimited?: boolean;
}
export interface Coverage {
  groups: {
    id: string;
    name: string;
    state: string;
    label: string;
    count: number;
    counts: Record<string, number>;
    files: (Item & { state: string })[];
    evidence: string;
    note: string;
  }[];
  podCount: number;
  podsWithLogs: number;
  warnings: string[];
}
