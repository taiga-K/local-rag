import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { retrieveChunks, type RetrieveChunk, type RetrieveResult, type Summary } from "./api";
import { Glyph } from "./glyphs";

type Entry =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "result"; query: string; result: RetrieveResult; error?: never }
  | { id: number; role: "result"; query: string; error: string; result?: never };

export function ChatScreen({ summary }: { summary: Summary }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [query, setQuery] = useState("");
  const [kbId, setKbId] = useState("");
  const [sending, setSending] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const folderNames = new Map(summary.folders.map((folder) => [folder.id, folder.name]));

  useEffect(() => {
    const last = entries.at(-1);
    if (last?.role === "result") {
      document.getElementById(`chat-entry-${last.id}`)?.scrollIntoView({ block: "start" });
    } else {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [entries, sending]);

  async function submit() {
    const text = query.trim();
    if (!text || sending) {
      return;
    }
    const userId = nextId.current++;
    const resultId = nextId.current++;
    setEntries((current) => [...current, { id: userId, role: "user", text }]);
    setQuery("");
    setSending(true);
    try {
      const result = await retrieveChunks(text, kbId || undefined);
      setEntries((current) => [...current, { id: resultId, role: "result", query: text, result }]);
    } catch (cause: unknown) {
      const error = cause instanceof Error ? cause.message : "検索に失敗しました";
      setEntries((current) => [...current, { id: resultId, role: "result", query: text, error }]);
    } finally {
      setSending(false);
    }
  }

  function submitForm(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <div className="col chat-page">
      <div className="chat-head">
        <div>
          <h1>チャットで確認</h1>
          <p className="chat-lead">クエリを投げて、返ってくる関連チャンクをそのまま確認できます。回答文の生成はしません。</p>
        </div>
        <label className="chat-scope">
          <span>検索対象</span>
          <select value={kbId} onChange={(event) => setKbId(event.target.value)}>
            <option value="">すべてのフォルダ</option>
            {summary.folders.map((folder) => (
              <option key={folder.id} value={folder.id}>{folder.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="chat-log" aria-live="polite">
        {entries.length === 0 && !sending ? (
          <div className="chat-empty">
            <span className="ic">{Glyph.search}</span>
            <p>例: 取り込んだファイルに含まれる語句を入力すると、一致した本文チャンク、ファイル名、スコアが表示されます。</p>
          </div>
        ) : null}
        {entries.map((entry) => entry.role === "user" ? (
          <div className="chat-row user" key={entry.id}>
            <div className="bubble user-bubble">{entry.text}</div>
          </div>
        ) : (
          <ResultMessage key={entry.id} entry={entry} folderNames={folderNames} />
        ))}
        {sending ? (
          <div className="chat-row">
            <div className="bubble answer-bubble pending"><span className="ic spin">{Glyph.sync}</span>検索中…</div>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      <form className="chat-input" onSubmit={submitForm}>
        <textarea
          aria-label="クエリ"
          placeholder="クエリを入力（Enterで送信、Shift+Enterで改行）"
          value={query}
          rows={2}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={keyDown}
        />
        <button className="chat-send" type="submit" disabled={!query.trim() || sending}>送信</button>
      </form>
    </div>
  );
}

function ResultMessage({ entry, folderNames }: { entry: Extract<Entry, { role: "result" }>; folderNames: Map<string, string> }) {
  if (entry.error) {
    return (
      <div className="chat-row" id={`chat-entry-${entry.id}`}>
        <div className="bubble answer-bubble error">
          <span className="ic bad">{Glyph.err}</span>
          <span>{entry.error}</span>
        </div>
      </div>
    );
  }
  const chunks = entry.result?.chunks ?? [];
  return (
    <div className="chat-row" id={`chat-entry-${entry.id}`}>
      <div className="bubble answer-bubble">
        <div className="answer-title">
          {chunks.length > 0 ? `${chunks.length}件の関連チャンク` : "一致するチャンクはありません"}
        </div>
        <div className="answer-query">クエリ: {entry.query}</div>
        {chunks.map((chunk, index) => (
          <ChunkCard key={chunk.id} chunk={chunk} index={index} folderNames={folderNames} />
        ))}
        <details className="raw-response">
          <summary>レスポンスJSON</summary>
          <pre>{JSON.stringify(entry.result, null, 2)}</pre>
        </details>
      </div>
    </div>
  );
}

function ChunkCard({ chunk, index, folderNames }: { chunk: RetrieveChunk; index: number; folderNames: Map<string, string> }) {
  const folder = folderNames.get(chunk.record.connector) ?? chunk.record.connector;
  const similarity = chunk.similarity === null ? "不明" : `${Math.round(chunk.similarity * 100)}%`;
  return (
    <article className="chunk-card">
      <div className="chunk-head">
        <span className="rank">#{index + 1}</span>
        <span className="file-name">{chunk.record.name}</span>
        <span className="chunk-meta">{folder}</span>
      </div>
      <p>{chunk.text}</p>
      <div className="chunk-stats">
        <span>類似度 {similarity}</span>
        <span>融合スコア {chunk.score.toFixed(4)}</span>
        {chunk.citation.blockIndex !== null ? <span>ブロック {chunk.citation.blockIndex + 1}</span> : null}
      </div>
    </article>
  );
}
