import { useEffect, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { HStack } from "@astryxdesign/core/HStack";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { VStack } from "@astryxdesign/core/VStack";
import { loadSettings, listKnowledgeBases, loadStatus, reindexConnector, saveSettings, type RecordRow } from "./api";
import { SCREENS, SettingsSaver, autoIndexCopy, countRows, foldersText, parseFolders, type AppliedSettings, type ScreenId, type SettingsDraft } from "./view";

export function App() {
  const [screen, setScreen] = useState<ScreenId>("folders");
  const [folders, setFolders] = useState("");
  const [includeSubfolders, setIncludeSubfolders] = useState(true);
  const [autoIndex, setAutoIndex] = useState(true);
  const [kbId, setKbId] = useState("");
  const [message, setMessage] = useState("");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [records, setRecords] = useState<RecordRow[]>([]);
  const draftRef = useRef<SettingsDraft>({ folders: "", includeSubfolders: true, autoIndex: true });
  const saverRef = useRef<SettingsSaver | null>(null);
  if (saverRef.current === null) {
    saverRef.current = new SettingsSaver();
  }
  draftRef.current = { folders, includeSubfolders, autoIndex };

  useEffect(() => {
    void loadSettings().then((settings) => {
      setFolders(foldersText(settings.folders));
      setIncludeSubfolders(settings.includeSubfolders);
      setAutoIndex(settings.autoIndex);
    }).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "設定を読めません"));
    void listKnowledgeBases().then((body) => {
      const first = body.knowledgeBases[0];
      if (first) {
        setKbId((current) => current || first.id);
      }
    }).catch(() => undefined);
  }, []);

  async function persist(next: SettingsDraft): Promise<SettingsDraft> {
    const saved = await saveSettings({
      folders: parseFolders(next.folders),
      includeSubfolders: next.includeSubfolders,
      autoIndex: next.autoIndex,
    });
    return {
      folders: foldersText(saved.folders),
      includeSubfolders: saved.includeSubfolders,
      autoIndex: saved.autoIndex,
    };
  }

  function applyPartial(result: AppliedSettings) {
    const next = { ...draftRef.current };
    if (result.folders !== undefined) {
      next.folders = result.folders;
    }
    if (result.includeSubfolders !== undefined) {
      next.includeSubfolders = result.includeSubfolders;
    }
    if (result.autoIndex !== undefined) {
      next.autoIndex = result.autoIndex;
    }
    draftRef.current = next;
    setFolders(next.folders);
    setIncludeSubfolders(next.includeSubfolders);
    setAutoIndex(next.autoIndex);
    setMessage(result.message);
  }

  async function refreshStatus() {
    if (!kbId) {
      setMessage("知識ベースがありません");
      return;
    }
    const status = await loadStatus(kbId);
    setCounts(status.counts);
    setRecords(status.records);
  }

  const copy = autoIndexCopy(autoIndex);
  return (
    <VStack gap={3}>
      <Heading level={1}>索引の設定</Heading>
      <HStack gap={2}>
        {SCREENS.map((item) => (
          <Button key={item.id} label={item.title} onClick={() => setScreen(item.id)} />
        ))}
      </HStack>
      {screen === "folders" ? (
        <VStack gap={2}>
          <Text>取り込むフォルダを1行に1つ書きます。下の階層も含めるかは次のボタンです。</Text>
          <TextArea
            label="フォルダ"
            value={folders}
            rows={4}
            onChange={(value) => {
              draftRef.current = { ...draftRef.current, folders: value };
              setFolders(value);
            }}
          />
          <Button
            label={includeSubfolders ? "下の階層も含める" : "そのフォルダだけ"}
            onClick={() => {
              const next = !draftRef.current.includeSubfolders;
              void saverRef.current?.save(() => draftRef.current, { includeSubfolders: next }, persist, "includeSubfolders").then(applyPartial);
            }}
          />
          <Button
            label="保存"
            onClick={() => {
              void saverRef.current?.save(() => draftRef.current, {}, persist, "folders").then(applyPartial);
            }}
          />
        </VStack>
      ) : null}
      {screen === "index" ? (
        <VStack gap={2}>
          <Heading level={2}>{copy.title}</Heading>
          <Text>{copy.detail}</Text>
          <Button
            label={autoIndex ? "自動索引を止める" : "自動索引を始める"}
            onClick={() => {
              const next = !draftRef.current.autoIndex;
              void saverRef.current?.save(() => draftRef.current, { autoIndex: next }, persist, "autoIndex").then(applyPartial);
            }}
          />
          <TextInput label="知識ベース" value={kbId} onChange={(value) => setKbId(value)} />
          <Button
            label="再索引"
            onClick={() => {
              void reindexConnector(kbId)
                .then((body) => setMessage(`${body.queued} 件を索引待ちにしました`))
                .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "再索引に失敗しました"));
            }}
          />
        </VStack>
      ) : null}
      {screen === "status" ? (
        <VStack gap={2}>
          <TextInput label="知識ベース" value={kbId} onChange={(value) => setKbId(value)} />
          <Button label="状況を読む" onClick={() => void refreshStatus().catch((error: unknown) => setMessage(error instanceof Error ? error.message : "状況を読めません"))} />
          {countRows(counts).map((row) => (
            <Text key={row.status}>{`${row.status} ${row.count}`}</Text>
          ))}
          {records.map((row) => (
            <Text key={row.recordId}>{`${row.recordName} ${row.indexingStatus}${row.failureReason ? ` ${row.failureReason}` : ""}`}</Text>
          ))}
        </VStack>
      ) : null}
      <Text>{message}</Text>
    </VStack>
  );
}
