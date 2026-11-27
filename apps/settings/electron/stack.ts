import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export const COMPOSE_PROJECT = "kbindex";
export const HEALTH_URL = "http://127.0.0.1:43123/api/v1/health/services";
export const POLL_MS = 5_000;
export const DEADLINE_MS = 420_000;
export const REQUIRED_SERVICES = ["postgres", "redis", "qdrant"] as const;
export const CLONE_MARKERS = ["docker-compose.yml", "Dockerfile", "pyproject.toml"] as const;

export type ExecResult = { code: number; stdout: string; stderr: string };
export type Exec = (command: string, args: string[], cwd?: string) => Promise<ExecResult>;

export type DockerLaunch =
  | { mode: "host"; command: "docker" }
  | { mode: "wsl"; command: "wsl.exe" };

export function windowsToWslPath(input: string): string {
  const normalized = input.replace(/\\/g, "/");
  const match = /^([A-Za-z]):(?:\/(.*))?$/.exec(normalized);
  if (!match) {
    return normalized;
  }
  const rest = match[2] ?? "";
  return `/mnt/${match[1].toLowerCase()}${rest ? `/${rest}` : ""}`;
}

export function missingCloneFiles(names: readonly string[]): string[] {
  return CLONE_MARKERS.filter((name) => !names.includes(name));
}

export function initialEnvText(): string {
  return "COMPOSE_PROJECT_NAME=kbindex\n";
}

export function volumesToRemove(names: readonly string[], deletePostgres: boolean): string[] {
  if (deletePostgres) {
    return [...names];
  }
  return names.filter((name) => name !== `${COMPOSE_PROJECT}_postgres_data`);
}

export function healthReady(body: unknown): { ready: boolean; status: string; services: Record<string, string> } {
  const record = body && typeof body === "object" ? body as { status?: unknown; services?: unknown } : {};
  const status = typeof record.status === "string" ? record.status : "unhealthy";
  const services: Record<string, string> = {};
  if (record.services && typeof record.services === "object") {
    for (const [key, value] of Object.entries(record.services)) {
      if (typeof value === "string") {
        services[key] = value;
      }
    }
  }
  const ready = status === "healthy" && REQUIRED_SERVICES.every((name) => services[name] === "healthy");
  return { ready, status, services };
}

export function composeUpArgs(launch: DockerLaunch, clonePath: string): { command: string; args: string[]; cwd?: string } {
  const envFile = path.join(clonePath, ".env");
  if (launch.mode === "host") {
    return {
      command: "docker",
      cwd: clonePath,
      args: ["compose", "-p", COMPOSE_PROJECT, "--env-file", envFile, "up", "-d", "--build"],
    };
  }
  return {
    command: "wsl.exe",
    args: [
      "-e", "docker", "compose",
      "-p", COMPOSE_PROJECT,
      "--project-directory", windowsToWslPath(clonePath),
      "--env-file", windowsToWslPath(envFile),
      "up", "-d", "--build",
    ],
  };
}

export async function detectDocker(exec: Exec, platform: NodeJS.Platform): Promise<DockerLaunch | { error: string }> {
  const hostInfo = await exec("docker", ["info"]);
  const hostCompose = await exec("docker", ["compose", "version"]);
  if (hostInfo.code === 0 && hostCompose.code === 0) {
    return { mode: "host", command: "docker" };
  }
  if (platform !== "win32") {
    const detail = [hostInfo.stderr, hostCompose.stderr, hostInfo.stdout].map((item) => item.trim()).find(Boolean);
    return { error: detail || "docker が見つかりません" };
  }
  const wslInfo = await exec("wsl.exe", ["-e", "docker", "info"]);
  const wslCompose = await exec("wsl.exe", ["-e", "docker", "compose", "version"]);
  if (wslInfo.code === 0 && wslCompose.code === 0) {
    return { mode: "wsl", command: "wsl.exe" };
  }
  const detail = [wslInfo.stderr, hostInfo.stderr, wslInfo.stdout].map((item) => item.trim()).find(Boolean);
  return { error: detail || "docker が見つかりません" };
}

export function ensureEnv(clonePath: string): { created: boolean } {
  const envFile = path.join(clonePath, ".env");
  if (fs.existsSync(envFile)) {
    return { created: false };
  }
  fs.writeFileSync(envFile, initialEnvText(), "utf8");
  return { created: true };
}

export function readSavedClone(userData: string): string | null {
  const file = path.join(userData, "clone-path.json");
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as { path?: unknown };
    return typeof parsed.path === "string" && parsed.path.trim() ? parsed.path : null;
  } catch {
    return null;
  }
}

export function writeSavedClone(userData: string, clonePath: string): void {
  fs.mkdirSync(userData, { recursive: true });
  const file = path.join(userData, "clone-path.json");
  const next = `${JSON.stringify({ path: clonePath })}\n`;
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, next, "utf8");
  fs.renameSync(temporary, file);
}

export function inspectClone(clonePath: string): { ok: true } | { ok: false; reason: string } {
  let names: string[];
  try {
    names = fs.readdirSync(clonePath);
  } catch {
    return { ok: false, reason: "フォルダを読めません" };
  }
  const missing = missingCloneFiles(names);
  if (missing.length > 0) {
    return { ok: false, reason: `このフォルダには ${missing.join(", ")} がありません` };
  }
  return { ok: true };
}

export function spawnExec(command: string, args: string[], cwd?: string): Promise<ExecResult> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      resolve({ code: 127, stdout, stderr: `${stderr}${error.message}` });
    });
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

export async function pollHealth(
  load: () => Promise<unknown>,
  wait: (ms: number) => Promise<void>,
  deadlineMs = DEADLINE_MS,
): Promise<{ ready: boolean; elapsedMs: number; status: string; services: Record<string, string>; error: string }> {
  const started = Date.now();
  let last = { ready: false, status: "unhealthy", services: {} as Record<string, string> };
  let error = "";
  while (Date.now() - started <= deadlineMs) {
    try {
      last = healthReady(await load());
      error = "";
      if (last.ready) {
        return { ...last, elapsedMs: Date.now() - started, error };
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : "health";
    }
    const remaining = deadlineMs - (Date.now() - started);
    if (remaining <= 0) {
      break;
    }
    await wait(Math.min(POLL_MS, remaining));
  }
  return { ...last, elapsedMs: Date.now() - started, error };
}
