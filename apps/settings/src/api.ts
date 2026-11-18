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
};

async function send(path: string, method: string, body?: unknown): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} returned ${response.status}`);
  }
  return response.json();
}

export function loadSettings(): Promise<LocalSettings> {
  return send("/api/v1/settings/local", "GET") as Promise<LocalSettings>;
}

export function saveSettings(settings: LocalSettings): Promise<LocalSettings> {
  return send("/api/v1/settings/local", "PUT", settings) as Promise<LocalSettings>;
}

export function listKnowledgeBases(): Promise<{ knowledgeBases: { id: string; name: string }[] }> {
  return send("/api/v1/kb", "GET") as Promise<{ knowledgeBases: { id: string; name: string }[] }>;
}

export function reindexConnector(kbId: string): Promise<{ queued: number }> {
  return send(`/api/v1/connectors/${encodeURIComponent(kbId)}/reindex`, "POST", {}) as Promise<{ queued: number }>;
}

export function loadStatus(kbId: string): Promise<{ counts: Record<string, number>; records: RecordRow[] }> {
  return Promise.all([
    send(`/api/v1/kb/${encodeURIComponent(kbId)}/indexing/counts`, "GET") as Promise<Record<string, number>>,
    send(`/api/v1/kb/${encodeURIComponent(kbId)}/records`, "GET") as Promise<{ records: RecordRow[] }>,
  ]).then(([counts, listed]) => ({ counts, records: listed.records }));
}
