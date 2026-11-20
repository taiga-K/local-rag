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
const OTHER_MODEL = "__other__";
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
  const [nextDimension, setNextDimension] = useState("");
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
    const raw = textRef.current.trim();
    const number = Number(raw);
    const numberOk = raw !== "" && Number.isFinite(number) && number >= -1 && number <= 1;
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
  const typedDimension = Number(nextDimension);
  const dimensionOk = Number.isInteger(typedDimension) && typedDimension >= 1;
  const modelNotice = points != null && points > 0
    ? "点が残っているあいだ、モデルは変えられません。"
    : "新しいモデルの次元を入れてください。今のモデルの次元は使いません。再起動すると反映されます。";

  return (
    <>
      <div className="backdrop" data-open={open ? "true" : "false"} onClick={onClose} />
      <div className="modal" data-open={open ? "true" : "false"} role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="modal-side">
          {CATS.map((item) => (
            <button key={item} className={cat === item ? "nav-row is-selected" : "nav-row"} type="button" onClick={() => setCat(item)}>
              <span className="t">{item}</span>
            </button>
          ))}
        </div>
        <div className="modal-main">
          <h2 id="settings-title" className="page-title">{cat}</h2>
          {cat === "取り込み" && local ? (
            <SettingRow
              name="自動で取り込む"
              desc={local.autoIndex ? "取り込んだ文書はすぐ索引されます。" : "新しい文書は索引されず、再索引で進みます。"}
            >
              <Switch
                on={local.autoIndex}
                onChange={(next) => {
                  const previous = local;
                  const saved = { ...local, autoIndex: next };
                  setLocal(saved);
                  void saveSettings(saved).catch((error: unknown) => {
                    setLocal(previous);
                    setNote(error instanceof Error ? error.message : "保存に失敗しました");
                  });
                }}
              />
            </SettingRow>
          ) : null}
          {cat === "索引" && embedding ? (
            <>
              <SettingRow name="埋め込みモデル" desc="実行中のプロセスは、再起動するまで今のモデルのままです。点が残っているあいだは変えられません。">
                <div className="control-col">
                  <select
                    className="field mono"
                    value={model}
                    aria-label="埋め込みモデル"
                    onChange={(event) => {
                      const next = event.target.value;
                      setDevice(embedding.requestedDevice || embedding.device);
                      setModel(next);
                      if (next === OTHER_MODEL) {
                        setNotice("model");
                        return;
                      }
                      setOtherModel("");
                      setNotice(next === embedding.model ? null : "model");
                    }}
                  >
                    {embedding.models.map((item) => <option key={item} value={item}>{item}</option>)}
                    <option value={OTHER_MODEL}>別のモデルを追加…</option>
                  </select>
                  {model === OTHER_MODEL ? (
                    <input
                      className="field"
                      aria-label="別のモデル名"
                      value={otherModel}
                      placeholder="モデル名"
                      onChange={(event) => setOtherModel(event.target.value)}
                    />
                  ) : null}
                </div>
              </SettingRow>
              <Impact
                open={notice === "model"}
                text={modelNotice}
                extra={notice === "model" && (points == null || points === 0) ? (
                  <input
                    className="field num"
                    aria-label="新しいモデルの次元"
                    inputMode="numeric"
                    placeholder="次元"
                    value={nextDimension}
                    onChange={(event) => setNextDimension(event.target.value)}
                  />
                ) : null}
                canApply={(points == null || points === 0) && dimensionOk && (model !== OTHER_MODEL || otherModel.trim() !== "")}
                onCancel={() => {
                  setModel(embedding.model);
                  setOtherModel("");
                  setNextDimension("");
                  setNotice(null);
                }}
                onApply={() => {
                  const chosen = model === OTHER_MODEL ? otherModel.trim() : model;
                  void saveEmbeddingModel(chosen, typedDimension).then((body) => {
                    setNotice(null);
                    setOtherModel("");
                    setNextDimension("");
                    setModel(chosen);
                    setEmbedding({ ...embedding, model: chosen, requestedModel: chosen });
                    if (body.restartRequired) {
                      setNote("再起動すると反映されます。");
                    }
                  }).catch((error: unknown) => setNote(error instanceof Error ? error.message : "変更できませんでした"));
                }}
              />
              <SettingRow name="計算に使う装置" desc="起動中の処理は、次に起動するまで今の装置のまま動きます。">
                <select
                  className="field"
                  value={device}
                  aria-label="計算に使う装置"
                  onChange={(event) => {
                    const next = event.target.value;
                    setModel(embedding.model);
                    setOtherModel("");
                    setNextDimension("");
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
                    setEmbedding({ ...embedding, requestedDevice: device });
                    setNotice(null);
                    setNote("再起動すると反映されます。");
                  }).catch((error: unknown) => {
                    setDevice(previous);
                    setNote(error instanceof Error ? error.message : "変更できませんでした");
                  });
                }}
              />
              <SettingRow name="キーワード検索の方式" desc="いま選べるのは fastembed だけです。">
                <select className="field" value={embedding.keyword} aria-label="キーワード検索の方式" disabled>
                  <option value={embedding.keyword}>{embedding.keyword}</option>
                </select>
              </SettingRow>
            </>
          ) : null}
          {cat === "検索結果" && retrieve ? (
            <>
              <SettingRow
                name="類似度で絞り込む"
                desc="質問との類似度が低い文書を検索結果から外します。結果が0件になることがあります。"
              >
                <Switch
                  on={retrieve.scoreThresholdEnabled}
                  onChange={(next) => commitThreshold(next)}
                />
              </SettingRow>
              {retrieve.scoreThresholdEnabled ? (
                <div className="set-row is-child">
                  <div className="copy">
                    <div className="name">しきい値</div>
                    <div className="desc">-1〜1の値。初期値は0.84です。</div>
                  </div>
                  <input
                    className="field num"
                    aria-label="しきい値"
                    inputMode="decimal"
                    value={thresholdText}
                    onChange={(event) => setThresholdText(event.target.value)}
                    onBlur={() => commitThreshold(true)}
                  />
                </div>
              ) : null}
            </>
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
      <div className="copy">
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
  extra = null,
  canApply = true,
  onCancel,
  onApply,
}: {
  open: boolean;
  text: string;
  extra?: ReactNode;
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
        <div className="notice__body">
          <div className="type-body-wrap">{text}</div>
          {extra}
          <div className="acts">
            {canApply ? <button className="primary" type="button" onClick={onApply}>変更する</button> : null}
            <button className="quiet" type="button" onClick={onCancel}>キャンセル</button>
          </div>
        </div>
      </div>
    </div>
  );
}
