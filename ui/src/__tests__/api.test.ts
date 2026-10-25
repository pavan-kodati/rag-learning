import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, describeError, request, setSession, setUnauthorizedHandler } from "../api";

function respond(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "content-type": "application/problem+json", ...headers } });
}

describe("api client", () => {
  beforeEach(() => { setSession(null); window.localStorage.clear(); });
  afterEach(() => { vi.restoreAllMocks(); setUnauthorizedHandler(null); });

  it("turns problem+json into an ApiError with the request id and field errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(422, { code: "validation_failed", detail: "title: required", request_id: "r-1", errors: [{ field: "title", message: "required" }] })));
    const err: any = await request("/matters").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, code: "validation_failed", requestId: "r-1", fields: [{ field: "title", message: "required" }] });
    expect(describeError(err)).toBe("title: required");
  });

  it("explains server errors with the request id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(500, { code: "internal_error", request_id: "abc" })));
    const err: any = await request("/x").catch((e) => e);
    expect(describeError(err)).toContain("request abc");
    expect(describeError(err)).toContain("server had a problem");
  });

  it("reports an unreachable server in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err: any = await request("/x").catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: "network" });
    expect(err.message).toMatch(/Cannot reach the server/);
  });

  it("friendly message for rate limiting", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(429, { code: "rate_limited" })));
    expect(((await request("/x").catch((e) => e)) as any).message).toMatch(/Too many requests/);
  });

  it("sends the bearer token and calls the unauthorised handler on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(401, { code: "unauthorized", detail: "expired" }));
    vi.stubGlobal("fetch", fetchMock);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setSession({ username: "a", role: "analyst", token: "tok" });
    await request("/matters").catch(() => undefined);
    expect((fetchMock.mock.calls[0][1].headers as Headers).get("Authorization")).toBe("Bearer tok");
    expect(handler).toHaveBeenCalledOnce();
  });

  it("handles empty 204 responses and text bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(new Response("plain", { status: 200, headers: { "content-type": "text/plain" } })));
    expect(await request("/a")).toBeUndefined();
    expect(await request("/b")).toBe("plain");
  });

  it("builds query strings without empty values and encodes the rest", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetchMock);
    await api.view("m1", "directions", { as_of: 2, today: "", status: undefined });
    await api.legal("m1", "penalty & damages", 3);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/matters/m1/directions?as_of=2");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/matters/m1/legal?q=penalty%20%26%20damages&as_of=3");
  });

  it("posts JSON and multipart bodies correctly", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetchMock);
    await api.ask("m1", "hello", 2);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ question: "hello", as_of_batch_seq: 2 });
    await api.upload("m1", 1, [new File(["x"], "a.pdf")]);
    expect(fetchMock.mock.calls[1][1].body).toBeInstanceOf(FormData);
    expect((fetchMock.mock.calls[1][1].headers as Headers).get("Content-Type")).toBeNull();
  });

  it("puts the access token on image and PDF links", () => {
    setSession({ username: "a", role: "viewer", token: "t k" });
    expect(api.pageImageUrl("d1", 2)).toContain("access_token=t%20k");
    expect(api.pdfUrl("d1")).toBe("/api/v1/documents/d1/pdf?access_token=t%20k");
    setSession(null);
    expect(api.pdfUrl("d1")).toBe("/api/v1/documents/d1/pdf");
  });

  it("survives a corrupt stored session", async () => {
    window.localStorage.setItem("lw.session", "{not json");
    const { loadSession } = await import("../api");
    expect(loadSession()).toBeNull();
  });
});
