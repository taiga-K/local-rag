import { afterEach, describe, expect, it, vi } from "vitest";
import { retrieveChunks } from "./api";

describe("retrieveChunks", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts a retrieve query with the selected folder as the kb filter", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ chunks: [], incomplete: false })));
    vi.stubGlobal("fetch", fetchMock);

    await retrieveChunks("東京の天気", "notes");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:43123/api/v1/retrieve", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        query: "東京の天気",
        limit: 8,
        rewriteQuery: false,
        maxChunksPerRecord: 3,
        filters: { kb: ["notes"] },
      }),
    });
  });

  it("searches every folder when no folder is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ chunks: [], incomplete: false })));
    vi.stubGlobal("fetch", fetchMock);

    await retrieveChunks("東京の天気");

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ filters: {} });
  });
});
