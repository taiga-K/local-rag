export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:43123";

export type LocalSettings = {
  folders: string[];
  includeSubfolders: boolean;
  autoIndex: boolean;
};

export type RecordRow = {
  recordId: string;
  externalRecordId: string;
  recordName: string;
  indexingStatus: string;
  failureReason: string | null;
  failureClassified: boolean;
  failureMessage: string | null;
  sourceModifiedMs: number | null;
  updatedAt: string | null;
};

export type FolderCount = {
  id: string;
  name: string;
  total: number;
  failed: number;
  active: number;
  queued: number;
  completed: number;
  empty?: number;
  held?: number;
};

export type Summary = {
  total: number;
  done: number;
  active: number;
  queued: number;
  failed: number;
  held?: number;
  reindexCount: number;
  latestAt: string | null;
  etaText?: string | null;
  current: { recordName: string; kbId: string; kbName: string } | null;
  pause: { active: boolean; kind: string | null; until: string | null };
  folders: FolderCount[];
};

export type Activity = {
  hasMore: boolean;
  events: { at: string | null; folder: string; text: string; name?: string; kind?: string; status?: string }[];
};

export type EmbeddingInfo = {
  model: string;
  device: string;
  requestedModel: string | null;
  requestedDevice: string | null;
  keyword: string;
  keywordEnabled?: boolean;
  dimension: number;
  pointCount: number | null;
  models: string[];
  devices: string[];
};

export type ThresholdLevel = "off" | "weak" | "standard" | "strong" | "custom";

export type RetrieveSettings = {
  level: ThresholdLevel;
  value?: number;
  customValue?: number;
};

export type RetrieveChunk = {
  id: string;
  text: string;
  score: number;
  similarity: number | null;
  record: {
    recordId: string;
    name: string;
    connector: string;
    updatedAt: number | null;
  };
  citation: {
    blockIndex: number | null;
  };
};

export type RetrieveResult = {
  chunks: RetrieveChunk[];
  incomplete: boolean;
};

async function send(path: string, method: string, body?: unknown): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${method} ${path} returned ${response.status}`;
    try {
      const payload = (await response.json()) as { error?: { message?: string } };
      if (payload.error?.message) {
        detail = payload.error.message;
      }
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return response.json();
}

export function loadSettings(): Promise<LocalSettings> {
  return send("/api/v1/settings/local", "GET") as Promise<LocalSettings>;
}

export function saveSettings(settings: LocalSettings): Promise<LocalSettings> {
  return send("/api/v1/settings/local", "PUT", settings) as Promise<LocalSettings>;
}

export function loadSummary(): Promise<Summary> {
  return send("/api/v1/ingest/summary", "GET") as Promise<Summary>;
}

export function loadActivity(limit = 8): Promise<Activity> {
  return send(`/api/v1/ingest/activity?limit=${limit}`, "GET") as Promise<Activity>;
}

export function setPause(kind: string | null, until?: string | null): Promise<Summary["pause"]> {
  return send("/api/v1/ingest/pause", "PUT", { kind, until: until ?? null }) as Promise<Summary["pause"]>;
}

export function retryFailed(): Promise<{ queued: number }> {
  return send("/api/v1/ingest/retry-failed", "POST", {}) as Promise<{ queued: number }>;
}

export async function loadRecords(kbId: string, status?: string): Promise<RecordRow[]> {
  const pageSize = 200;
  const all: RecordRow[] = [];
  const statusQuery = status ? `&status=${encodeURIComponent(status)}` : "";
  for (let offset = 0; ; offset += pageSize) {
    const body = (await send(
      `/api/v1/kb/${encodeURIComponent(kbId)}/records?limit=${pageSize}&offset=${offset}${statusQuery}`,
      "GET",
    )) as { records: RecordRow[] };
    all.push(...body.records);
    if (body.records.length < pageSize) {
      return all;
    }
  }
}

export function reprocessRecord(kbId: string, externalRecordId: string): Promise<unknown> {
  return send(
    `/api/v1/kb/${encodeURIComponent(kbId)}/records/${encodeURIComponent(externalRecordId)}/reprocess`,
    "POST",
    {},
  );
}

export function detachKb(kbId: string): Promise<{ deleted: number }> {
  return send(`/api/v1/kb/${encodeURIComponent(kbId)}/detach`, "POST", {}) as Promise<{ deleted: number }>;
}

export function loadRetrieveSettings(): Promise<RetrieveSettings> {
  return send("/api/v1/settings/retrieve", "GET") as Promise<RetrieveSettings>;
}

export function saveRetrieveSettings(settings: RetrieveSettings): Promise<RetrieveSettings> {
  return send("/api/v1/settings/retrieve", "PUT", settings) as Promise<RetrieveSettings>;
}

export function loadEmbedding(): Promise<EmbeddingInfo> {
  return send("/api/v1/engineer/embedding", "GET") as Promise<EmbeddingInfo>;
}

export function saveEmbeddingModel(
  model: string,
  dimension: number,
): Promise<{ model: string; restartRequired?: boolean }> {
  return send("/api/v1/engineer/embedding", "PUT", { model, dimension }) as Promise<{
    model: string;
    restartRequired?: boolean;
  }>;
}

export function saveDevice(device: string): Promise<unknown> {
  return send("/api/v1/engineer/device", "PUT", { device });
}

export function saveKeyword(enabled: boolean): Promise<EmbeddingInfo> {
  return send("/api/v1/engineer/keyword", "PUT", { enabled }) as Promise<EmbeddingInfo>;
}

export function retrieveChunks(query: string, kbId?: string): Promise<RetrieveResult> {
  return send("/api/v1/retrieve", "POST", {
    query,
    limit: 8,
    rewriteQuery: false,
    maxChunksPerRecord: 3,
    filters: kbId ? { kb: [kbId] } : {},
  }) as Promise<RetrieveResult>;
}
