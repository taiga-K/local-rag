import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  loadEmbedding,
  loadRetrieveSettings,
  loadSettings,
  saveDevice,
  saveEmbeddingModel,
  saveRetrieveSettings,
  saveSettings,
  type EmbeddingInfo,
  type LocalSettings,
  type RetrieveSettings,
} from "./api";

const CATS = ["取り込み", "索引", "検索結果", "表示"] as const;
type Cat = (typeof CATS)[number];
type ThemeChoice = "system" | "light" | "dark";

export function SettingsDialog({
  onClose,
}: {
  onClose: () => void;
}) {
  const [cat, setCat] = useState<Cat>("検索結果");
  const [local, setLocal] = useState<LocalSettings | null>(null);
  const [retrieve, setRetrieve] = useState<RetrieveSettings | null>(null);
  const [embedding, setEmbedding] = useState<EmbeddingInfo | null>(null);
  const [model, setModel] = useState("");
  const [device, setDevice] = useState("");
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const [notice, setNotice] = useState<"model" | "device" | null>(null);
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const [thresholdText, setThresholdText] = useState("0.84");
  const [otherModel, setOtherModel] = useState("");
  const retrieveRef = useRef(retrieve);
  const textRef = useRef(thresholdText);
  const saveSeq = useRef(0);
  const saveChain = useRef(Promise.resolve());
  retrieveRef.current = retrieve;
  textRef.current = thresholdText;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setOpen(true));
    void Promise.all([loadSettings(), loadRetrieveSettings(), loadEmbedding()]).then(([settings, score, embed]) => {
      setLocal(settings);
      setRetrieve(score);
      setThresholdText(String(score.scoreThreshold));
      setEmbedding(embed);
      setModel(embed.model);
      setDevice(embed.requestedDevice || embed.device);
    }).catch((error: unknown) => setNote(error instanceof Error ? error.message : "設定を読めません"));
    const stored = window.localStorage.getItem("local-rag-theme");
    if (stored === "light" || stored === "dark" || stored === "system") {
      setTheme(stored);
    }
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function commitThreshold(enabled: boolean): void {
    const current = retrieveRef.current;
    if (!current) {
      return;
    }
    const number = Number(textRef.current);
    const numberOk = Number.isFinite(number) && number >= -1 && number <= 1;
    if (!numberOk) {
      setThresholdText(String(current.scoreThreshold));
      if (enabled === current.scoreThresholdEnabled) {
        return;
      }
    }
    const saved = {
      scoreThresholdEnabled: enabled,
      scoreThreshold: numberOk ? number : current.scoreThreshold,
    };
    const seq = saveSeq.current + 1;
    saveSeq.current = seq;
    retrieveRef.current = saved;
    setRetrieve(saved);
    saveChain.current = saveChain.current.then(async () => {
      try {
        const body = await saveRetrieveSettings(saved);
        if (saveSeq.current !== seq) {
          return;
        }
        retrieveRef.current = body;
        setRetrieve(body);
        setThresholdText(String(body.scoreThreshold));
      } catch (error: unknown) {
        if (saveSeq.current !== seq) {
          return;
        }
        retrieveRef.current = current;
        setRetrieve(current);
        setThresholdText(String(current.scoreThreshold));
        setNote(error instanceof Error ? error.message : "保存に失敗しました");
      }
    });
  }

  const points = embedding?.pointCount;
  const modelNotice = points != null && points > 0
    ? "点が残っているあいだ、モデルは変えられません。"
    : points === 0
      ? "再起動すると、このモデルに切り替わります。"
      : "点が残っていると変更は拒否されます。受け入れられたときは、再起動が必要です。";

  return (
    <>
      <div className="backdrop" data-open={open ? "true" : "false"} onClick={onClose} />
      <div className="modal" data-open={open ? "true" : "false"} role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="modal-side">
          <div className="cap">設定</div>
          {CATS.map((item) => (
            <button key={item} className={cat === item ? "nav-row is-selected" : "nav-row"} type="button" onClick={() => setCat(item)}>
              <span className="t">{item}</span>
            </button>
          ))}
        </div>
        <div className="modal-main">
          <h2 id="settings-title" style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}>{cat}</h2>
          <div className="rule" />
          {cat === "取り込み" && local ? (
            <SettingRow
              name="自動で取り込む"
              desc={local.autoIndex ? "取り込んだ文書はすぐ索引されます。" : "新しい文書は索引されず、再索引で進みます。"}
            >
              <Switch
                on={local.autoIndex}
                onChange={(next) => {
                  const saved = { ...local, autoIndex: next };
                  setLocal(saved);
                  void saveSettings(saved).catch((error: unknown) => setNote(error instanceof Error ? error.message : "保存に失敗しました"));
                }}
              />
            </SettingRow>
          ) : null}
          {cat === "索引" && embedding ? (
            <>
              <SettingRow name="埋め込みモデル" desc="実行中のプロセスは、再起動するまで今のモデルのままです。点が残っているあいだは変えられません。">
                <select
                  className="field"
                  value={model}
                  aria-label="埋め込みモデル"
                  onChange={(event) => {
                    const next = event.target.value;
                    setModel(next);
                    setNotice(next === embedding.model ? null : "model");
                  }}
                >
                  {embedding.models.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <input
                  className="field"
                  aria-label="別のモデル名"
                  value={otherModel}
                  placeholder="別のモデル名"
                  onChange={(event) => {
                    const next = event.target.value;
                    setOtherModel(next);
                    const chosen = next.trim();
                    setNotice(chosen && chosen !== embedding.model ? "model" : model !== embedding.model ? "model" : null);
                  }}
                />
              </SettingRow>
              <Impact
                open={notice === "model"}
                text={modelNotice}
                canApply={points == null || points === 0}
                onCancel={() => {
                  setModel(embedding.model);
                  setOtherModel("");
                  setNotice(null);
                }}
                onApply={() => {
                  const chosen = otherModel.trim() || model;
                  void saveEmbeddingModel(chosen, embedding.dimension).then((body) => {
                    setNotice(null);
                    setOtherModel("");
                    setModel(chosen);
                    setEmbedding({ ...embedding, model: chosen, requestedModel: chosen });
                    if (body.restartRequired) {
                      setNote("再起動すると反映されます。");
                    }
                  }).catch((error: unknown) => setNote(error instanceof Error ? error.message : "変更できませんでした"));
                }}
              />
              <SettingRow name="計算に使う装置" desc="実行中のプロセスは、再起動するまで今の装置のままです。">
                <select
                  className="field"
                  value={device}
                  aria-label="計算に使う装置"
                  onChange={(event) => {
                    const next = event.target.value;
                    setDevice(next);
                    setNotice(next === embedding.device ? null : "device");
                  }}
                >
                  {embedding.devices.map((item) => <option key={item} value={item}>{item === "cpu" ? "CPU" : "GPU"}</option>)}
                </select>
              </SettingRow>
              <Impact
                open={notice === "device"}
                text="再起動するまで、今の装置のままです。"
                onCancel={() => {
                  setDevice(embedding.requestedDevice || embedding.device);
                  setNotice(null);
                }}
                onApply={() => {
                  const previous = embedding.requestedDevice || embedding.device;
                  void saveDevice(device).then(() => {
                    setNotice(null);
                    setNote("再起動すると反映されます。");
                  }).catch((error: unknown) => {
                    setDevice(previous);
                    setNote(error instanceof Error ? error.message : "変更できませんでした");
                  });
                }}
              />
              <SettingRow name="キーワード検索の方式" desc="いま使える方式は fastembed だけです。">
                <select className="field" value={embedding.keyword} aria-label="キーワード検索の方式" disabled>
                  <option value={embedding.keyword}>{embedding.keyword}</option>
                </select>
              </SettingRow>
            </>
          ) : null}
          {cat === "検索結果" && retrieve ? (
            <SettingRow
              name="類似度のしきい値"
              desc={
                <>
                  オンにすると、質問との類似度がこの値より低い文書を検索結果から外します。結果が
                  <span className="nowrap">0件</span>
                  になることがあります。
                </>
              }
            >
              <span className="switch-line">
                <input
                  className={retrieve.scoreThresholdEnabled ? "field threshold-field num" : "field threshold-field num is-off"}
                  aria-label="類似度のしきい値"
                  inputMode="decimal"
                  disabled={!retrieve.scoreThresholdEnabled}
                  value={thresholdText}
                  onChange={(event) => setThresholdText(event.target.value)}
                  onBlur={() => commitThreshold(retrieveRef.current?.scoreThresholdEnabled ?? false)}
                />
                <Switch
                  on={retrieve.scoreThresholdEnabled}
                  onChange={(next) => commitThreshold(next)}
                />
              </span>
            </SettingRow>
          ) : null}
          {cat === "表示" ? (
            <SettingRow name="テーマ" desc="OSに合わせる、ライト、ダークから選びます。">
              <select
                className="field"
                aria-label="テーマ"
                value={theme}
                onChange={(event) => {
                  const next = event.target.value as ThemeChoice;
                  setTheme(next);
                  document.documentElement.dataset.theme = next;
                  window.localStorage.setItem("local-rag-theme", next);
                }}
              >
                <option value="system">OSに合わせる</option>
                <option value="light">ライト</option>
                <option value="dark">ダーク</option>
              </select>
            </SettingRow>
          ) : null}
          {note ? <p className="error-line">{note}</p> : null}
        </div>
      </div>
    </>
  );
}

function SettingRow({ name, desc, children }: { name: string; desc: ReactNode; children: ReactNode }) {
  return (
    <div className="set-row">
      <div>
        <div className="name">{name}</div>
        <div className="desc">{desc}</div>
      </div>
      {children}
    </div>
  );
}

function Switch({ on, onChange }: { on: boolean; onChange: (next: boolean) => void }) {
  return (
    <span className="switch-line">
      <button className="switch" type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}>
        <span className="switch__thumb" />
      </button>
      <span className="switch-word">{on ? "オン" : "オフ"}</span>
    </span>
  );
}

function Impact({
  open,
  text,
  canApply = true,
  onCancel,
  onApply,
}: {
  open: boolean;
  text: string;
  canApply?: boolean;
  onCancel: () => void;
  onApply: () => void;
}) {
  return (
    <div className="notice" data-open={open ? "true" : "false"} aria-live="polite">
      <div className="notice__inner">
        <svg className="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 7.25v4M8 4.75v.5" />
        </svg>
        <div>
          <div>{text}</div>
          <div className="acts">
            {canApply ? <button className="primary" type="button" onClick={onApply}>変更する</button> : null}
            <button className="quiet" type="button" onClick={onCancel}>キャンセル</button>
          </div>
        </div>
      </div>
    </div>
  );
}
