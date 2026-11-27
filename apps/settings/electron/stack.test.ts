import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  composeUpArgs,
  detectDocker,
  ensureEnv,
  healthReady,
  initialEnvText,
  inspectClone,
  missingCloneFiles,
  pollHealth,
  volumesToRemove,
  windowsToWslPath,
  writeSavedClone,
  readSavedClone,
} from "./stack";

describe("windowsToWslPath", () => {
  it("maps a drive letter to /mnt", () => {
    expect(windowsToWslPath("C:\\src\\local-rag")).toBe("/mnt/c/src/local-rag");
    expect(windowsToWslPath("D:/work")).toBe("/mnt/d/work");
  });
});

describe("clone and env", () => {
  it("names the files a clone must contain", () => {
    expect(missingCloneFiles(["docker-compose.yml", "Dockerfile", "pyproject.toml"])).toEqual([]);
    expect(missingCloneFiles(["Dockerfile"])).toEqual(["docker-compose.yml", "pyproject.toml"]);
  });

  it("reports a missing folder instead of throwing", () => {
    const missing = inspectClone(path.join(os.tmpdir(), "kbindex-missing-clone"));
    expect(missing.ok).toBe(false);
    if (!missing.ok) {
      expect(missing.reason).toBe("フォルダを読めません");
    }
  });

  it("writes .env once and leaves an existing file alone", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kbindex-env-"));
    expect(ensureEnv(dir)).toEqual({ created: true });
    expect(fs.readFileSync(path.join(dir, ".env"), "utf8")).toBe(initialEnvText());
    fs.writeFileSync(path.join(dir, ".env"), "COMPOSE_PROJECT_NAME=kept\n");
    expect(ensureEnv(dir)).toEqual({ created: false });
    expect(fs.readFileSync(path.join(dir, ".env"), "utf8")).toBe("COMPOSE_PROJECT_NAME=kept\n");
  });

  it("saves the clone path and reads it back", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kbindex-save-"));
    writeSavedClone(dir, "C:\\src\\local-rag");
    expect(readSavedClone(dir)).toBe("C:\\src\\local-rag");
    expect(readSavedClone(path.join(dir, "missing"))).toBeNull();
  });
});

describe("docker launch", () => {
  it("uses docker on PATH when info and compose both succeed", async () => {
    const launch = await detectDocker(async (command, args) => {
      if (command === "docker" && (args[0] === "info" || (args[0] === "compose" && args[1] === "version"))) {
        return { code: 0, stdout: "ok", stderr: "" };
      }
      return { code: 1, stdout: "", stderr: "no" };
    }, "win32");
    expect(launch).toEqual({ mode: "host", command: "docker" });
  });

  it("falls back to wsl.exe when docker is not on PATH", async () => {
    const launch = await detectDocker(async (command, args) => {
      if (command === "wsl.exe" && args[0] === "-e" && args[1] === "docker") {
        return { code: 0, stdout: "ok", stderr: "" };
      }
      return { code: 127, stdout: "", stderr: "not found" };
    }, "win32");
    expect(launch).toEqual({ mode: "wsl", command: "wsl.exe" });
    if ("mode" in launch && launch.mode === "wsl") {
      const up = composeUpArgs(launch, "C:\\src\\local-rag");
      expect(up.command).toBe("wsl.exe");
      expect(up.args).toContain("--project-directory");
      expect(up.args).toContain("/mnt/c/src/local-rag");
      expect(up.args).toContain("/mnt/c/src/local-rag/.env");
    }
  });

  it("does not try wsl.exe on linux", async () => {
    const launch = await detectDocker(async () => ({ code: 1, stdout: "", stderr: "missing" }), "linux");
    expect(launch).toEqual({ error: "missing" });
  });
});

describe("health poll", () => {
  it("is ready when the three stores are healthy and embedding is not", () => {
    const result = healthReady({
      status: "healthy",
      services: { postgres: "healthy", redis: "healthy", qdrant: "healthy", embedding: "unhealthy" },
    });
    expect(result.ready).toBe(true);
    expect(result.services.embedding).toBe("unhealthy");
  });

  it("is not ready when a store is down", () => {
    expect(healthReady({
      status: "unhealthy",
      services: { postgres: "unhealthy", redis: "healthy", qdrant: "healthy", embedding: "healthy" },
    }).ready).toBe(false);
  });

  it("stops at the deadline", async () => {
    const result = await pollHealth(async () => {
      throw new Error("down");
    }, async () => undefined, 0);
    expect(result.ready).toBe(false);
    expect(result.error).toBe("down");
  });
});

describe("uninstall volumes", () => {
  it("keeps the postgres volume unless asked", () => {
    const names = ["kbindex_postgres_data", "kbindex_redis_data", "kbindex_hf"];
    expect(volumesToRemove(names, false)).toEqual(["kbindex_redis_data", "kbindex_hf"]);
    expect(volumesToRemove(names, true)).toEqual(names);
  });
});
