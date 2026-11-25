import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  loadEmbedding,
  loadRetrieveSettings,
  loadSettings,
  saveDevice,
  saveEmbeddingModel,
  saveKeyword,
  saveRetrieveSettings,
  saveSettings,
  type EmbeddingInfo,
  type LocalSettings,
  type ThresholdLevel,
} from "./api";
import { syncFolders } from "./bridge";
import { Glyph } from "./glyphs";
import {
  THRESHOLD_ERROR,
  THRESHOLD_ROW_DESC,
  THRESHOLD_ROW_NAME,
  THRESHOLD_SEGMENTS,
  commitThresholdText,
  customSeed,
  persistThresholdLevel,
  stepThresholdCents,
  thresholdDraftIncomplete,
  thresholdWarning,
  tierBoxText,
} from "./threshold";

const MODEL_LABELS: Record<string, string> = {
  "cl-nagoya/ruri-v3-310m": "ruri v3（日本語向け・標準）",
  "cl-nagoya/ruri-v3-130m": "ruri v3（日本語向け・軽量）",
};

type ThemeChoice = "system" | "light" | "dark";

export function SettingsScreen() {
  const [local, setLocal] = useState<LocalSettings | null>(null);
  const [embedding, setEmbedding] = useState<EmbeddingInfo | null>(null);
  const [level, setLevel] = useState<ThresholdLevel>("off");
  const [customText, setCustomText] = useState("");
  const [savedCustom, setSavedCustom] = useState<number | null>(null);
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const [note, setNote] = useState("");
  const customInput = useRef<HTMLInputElement>(null);
  const customFocus = useRef(false);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const saveTicket = useRef(0);

  useEffect(() => {
    void Promise.all([loadSettings(), loadRetrieveSettings(), loadEmbedding()]).then(([settings, score, embed]) => {
      setLocal(settings);
      setLevel(score.level);
      const remembered = typeof score.customValue === "number"
        ? score.customValue
        : score.level === "custom" && typeof score.value === "number"
          ? score.value
          : null;
      setSavedCustom(remembered);
      setCustomText(score.level === "custom" && remembered !== null ? remembered.toFixed(2) : "");
      setEmbedding(embed);
    }).catch((error: unknown) => setNote(error instanceof Error ? error.message : "設定を読めません"));
    const stored = window.localStorage.getItem("local-rag-theme");
    if (stored === "light" || stored === "dark" || stored === "system") {
      setTheme(stored);
    }
  }, []);

  function enqueueSave(body: { level: ThresholdLevel; value?: number }, onError: () => void) {
    const run = saveQueue.current.then(() => saveRetrieveSettings(body)).then(
      () => undefined,
      (error: unknown) => {
        onError();
        setNote(error instanceof Error ? error.message : "保存に失敗しました");
      },
    );
    saveQueue.current = run.then(() => undefined, () => undefined);
  }

  function writeCustomCents(cents: number) {
    const value = cents / 100;
    const previous = savedCustom;
    const ticket = ++saveTicket.current;
    setSavedCustom(value);
    setCustomText(value.toFixed(2));
    enqueueSave({ level: persistThresholdLevel("custom", cents), value }, () => {
      if (ticket !== saveTicket.current) {
        return;
      }
      setSavedCustom(previous);
      setCustomText(previous === null ? "" : previous.toFixed(2));
    });
  }

  function commitCustom() {
    if (level !== "custom") {
      return;
    }
    if (thresholdDraftIncomplete(customText)) {
      setCustomText(savedCustom === null ? "" : savedCustom.toFixed(2));
      return;
    }
    const result = commitThresholdText(customText);
    if (!result.ok) {
      return;
    }
    writeCustomCents(result.cents);
  }

  function chooseLevel(next: ThresholdLevel) {
    if (next === level) {
      return;
    }
    if (next === "custom") {
      const previous = level === "weak" || level === "standard" || level === "strong" || level === "off" ? level : "off";
      const seeded = customSeed(previous, savedCustom);
      const seededCommit = commitThresholdText(seeded);
      setCustomText(seeded);
      customFocus.current = true;
      setLevel("custom");
      if (!seededCommit.ok) {
        return;
      }
      const value = seededCommit.cents / 100;
      const remembered = savedCustom;
      const ticket = ++saveTicket.current;
      setSavedCustom(value);
      enqueueSave({ level: persistThresholdLevel("custom", seededCommit.cents), value }, () => {
        if (ticket !== saveTicket.current) {
          return;
        }
        setSavedCustom(remembered);
        setLevel(previous);
        setCustomText(remembered === null ? "" : remembered.toFixed(2));
      });
      return;
    }
    const previous = level;
    setLevel(next);
    enqueueSave({ level: next }, () => setLevel(previous));
  }

  function stepCustom(direction: -1 | 1) {
    const parsed = commitThresholdText(customText);
    const base = parsed.ok ? parsed.cents : savedCustom === null ? null : Math.round(savedCustom * 100);
    if (base === null) {
      return;
    }
    writeCustomCents(stepThresholdCents(base, direction));
  }

  useEffect(() => {
    if (level !== "custom" || !customFocus.current) {
      return;
    }
    customFocus.current = false;
    customInput.current?.focus();
    customInput.current?.select();
  }, [level, customText]);

  const editing = level === "custom";
  const draft = editing ? commitThresholdText(customText) : null;
  const incomplete = editing && thresholdDraftIncomplete(customText);
  const customError = editing && !incomplete && draft !== null && !draft.ok ? THRESHOLD_ERROR : "";
  const customWarn = editing && !incomplete && draft !== null && draft.ok ? thresholdWarning(draft.cents) : "";
  const boxValue = editing ? customText : tierBoxText(level);
  const describedBy = customError || customWarn ? "threshold-status" : undefined;

  return (
    <div className="col set">
      <h1>設定</h1>
      <section style={{ marginTop: 24 }}>
        <div className="sec-head"><h2>取り込み</h2></div>
        <Row
          name="フォルダの変更を自動で取り込む"
          desc="オフにすると、概要の「今すぐ確認」を押したときだけ取り込みます。"
          control={
            <Toggle
              on={local?.autoIndex ?? false}
              onChange={(next) => {
                if (!local) {
                  return;
                }
                const saved = { ...local, autoIndex: next };
                setLocal(saved);
                void saveSettings(saved).then(() => (next ? syncFolders() : "")).then((problem) => {
                  if (problem) {
                    setNote(problem);
                  }
                }).catch((error: unknown) => {
                  setLocal(local);
                  setNote(error instanceof Error ? error.message : "保存に失敗しました");
                });
              }}
            />
          }
        />
      </section>
      <section>
        <div className="sec-head"><h2>検索の精度と速さ</h2></div>
        {embedding ? (
          <>
            <Row
              name="埋め込みモデル"
              desc="取り込み済みのデータがあるあいだは変更できません。モデルが変わると、これまでの索引では検索できなくなるためです。"
              control={
                <ModelSelect
                  embedding={embedding}
                  onError={setNote}
                  onSaved={(model) => setEmbedding((current) => {
                    if (!current) {
                      return current;
                    }
                    if (!model || model === current.model) {
                      return { ...current, requestedModel: null };
                    }
                    return {
                      ...current,
                      requestedModel: model,
                      models: current.models.includes(model) ? current.models : [...current.models, model],
                    };
                  })}
                />
              }
            />
            <Row
              name="計算に使う装置"
              desc="次に起動したときから切り替わります。"
              control={
                <Select
                  value={embedding.requestedDevice || embedding.device}
                  options={embedding.devices.map((item) => ({ value: item, label: item === "cpu" ? "CPU" : "GPU" }))}
                  onChange={(next) => {
                    const previous = embedding.requestedDevice || embedding.device;
                    setEmbedding((current) => (current ? { ...current, requestedDevice: next } : current));
                    void saveDevice(next).catch((error: unknown) => {
                      setEmbedding((current) => (current ? { ...current, requestedDevice: previous } : current));
                      setNote(error instanceof Error ? error.message : "変更できませんでした");
                    });
                  }}
                />
              }
            />
            <Row
              name="キーワードの一致でも探す"
              desc="文書の意味に加えて、言葉がそのまま含まれる文書も探します。"
              control={
                <Toggle
                  on={embedding.keywordEnabled !== false}
                  onChange={(next) => {
                    const previous = embedding.keywordEnabled !== false;
                    setEmbedding((current) => (current ? { ...current, keywordEnabled: next } : current));
                    void saveKeyword(next).catch((error: unknown) => {
                      setEmbedding((current) => (current ? { ...current, keywordEnabled: previous } : current));
                      setNote(error instanceof Error ? error.message : "保存に失敗しました");
                    });
                  }}
                />
              }
            />
          </>
        ) : null}
      </section>
      <section>
        <div className="sec-head"><h2>検索結果</h2></div>
        <div className="threshold-block">
        <div className="r threshold-row">
          <div className="grow">
            <span>{THRESHOLD_ROW_NAME}</span>
            <span className="d">{THRESHOLD_ROW_DESC}</span>
          </div>
          <div className="threshold-line">
              <div className="seg" role="radiogroup" aria-label={THRESHOLD_ROW_NAME}>
                {THRESHOLD_SEGMENTS.map((item) => (
                  <label key={item.id} className={item.id === level ? "on" : ""}>
                    <input
                      type="radio"
                      name="score-threshold-level"
                      value={item.id}
                      checked={item.id === level}
                      onChange={() => chooseLevel(item.id)}
                    />
                    {item.label}
                  </label>
                ))}
              </div>
              <input
                ref={customInput}
                id="threshold-value"
                className="threshold-box"
                inputMode="decimal"
                disabled={!editing}
                aria-invalid={customError !== ""}
                aria-describedby={describedBy}
                value={boxValue}
                onChange={(event) => setCustomText(event.target.value)}
                onBlur={commitCustom}
                onKeyDown={(event) => {
                  if (!editing) {
                    return;
                  }
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitCustom();
                    return;
                  }
                  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                    event.preventDefault();
                    stepCustom(event.key === "ArrowUp" ? 1 : -1);
                  }
                }}
              />
          </div>
        </div>
            {customWarn ? (
              <p id="threshold-status" className="threshold-note warn" role="status" aria-live="polite">
                {Glyph.warn}
                <span>{customWarn}</span>
              </p>
            ) : null}
            {customError ? (
              <p id="threshold-status" className="threshold-note err" role="status" aria-live="polite">
                <span>{customError}</span>
              </p>
            ) : null}
        </div>
      </section>
      <section>
        <div className="sec-head"><h2>表示</h2></div>
        <Row
          name="テーマ"
          desc=""
          control={
            <Select
              value={theme}
              options={[
                { value: "system", label: "Windows の設定に合わせる" },
                { value: "light", label: "ライト" },
                { value: "dark", label: "ダーク" },
              ]}
              onChange={(next) => {
                const choice = next as ThemeChoice;
                setTheme(choice);
                document.documentElement.dataset.theme = choice;
                window.localStorage.setItem("local-rag-theme", choice);
              }}
            />
          }
        />
      </section>
      {note ? <p className="error-line">{note}</p> : null}
    </div>
  );
}

function Row({ name, desc, control }: { name: string; desc: string; control: ReactNode }) {
  return (
    <div className="r">
      <div className="grow">
        <span>{name}</span>
        {desc ? <span className="d">{desc}</span> : null}
      </div>
      {control}
    </div>
  );
}

function Toggle({ on, onChange }: { on: boolean; onChange: (next: boolean) => void }) {
  return (
    <button className={on ? "toggle on" : "toggle"} type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}>
      {on ? "オン" : "オフ"}<i />
    </button>
  );
}

function Select({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (next: string) => void;
}) {
  return (
    <span className="select" style={{ padding: 0, position: "relative" }}>
      <select
        aria-label={options.find((item) => item.value === value)?.label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{ width: "100%", height: "100%", border: 0, background: "transparent", padding: "0 28px 0 12px", appearance: "none" }}
      >
        {options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
      <span style={{ position: "absolute", right: 10, display: "flex", pointerEvents: "none" }}>{Glyph.down}</span>
    </span>
  );
}

function ModelSelect({
  embedding,
  onError,
  onSaved,
}: {
  embedding: EmbeddingInfo;
  onError: (message: string) => void;
  onSaved: (model: string | null) => void;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [dimension, setDimension] = useState("");
  const label = (id: string) => MODEL_LABELS[id] ?? id;
  const typed = Number(dimension);
  const dimensionOk = Number.isInteger(typed) && typed >= 1;
  return (
    <span className="control-col">
      <Select
        value={pending ?? embedding.requestedModel ?? embedding.model}
        options={embedding.models.map((item) => ({ value: item, label: label(item) }))}
        onChange={(next) => {
          if (next === embedding.model) {
            setPending(null);
            if (embedding.requestedModel && embedding.requestedModel !== embedding.model) {
              void saveEmbeddingModel(embedding.model, embedding.dimension).then(() => {
                onSaved(null);
                onError("");
              }).catch((error: unknown) => onError(error instanceof Error ? error.message : "変更できませんでした"));
            }
            return;
          }
          if ((embedding.pointCount ?? 0) > 0) {
            onError("点が残っているあいだ、モデルは変えられません。");
            return;
          }
          setPending(next);
          onError("新しいモデルの次元を入れてください。再起動すると反映されます。");
        }}
      />
      {pending ? (
        <span className="pair">
          <input
            className="select"
            style={{ width: 96 }}
            aria-label="新しいモデルの次元"
            inputMode="numeric"
            placeholder="次元"
            value={dimension}
            onChange={(event) => setDimension(event.target.value)}
          />
          <button
            className="btn sm"
            type="button"
            disabled={!dimensionOk}
            onClick={() => {
              void saveEmbeddingModel(pending, typed).then(() => {
                onSaved(pending);
                setPending(null);
                setDimension("");
                onError("再起動すると反映されます。");
              }).catch((error: unknown) => onError(error instanceof Error ? error.message : "変更できませんでした"));
            }}
          >
            変更する
          </button>
        </span>
      ) : null}
    </span>
  );
}
