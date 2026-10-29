import { describe, expect, it, vi } from "vitest";

import { mockApi } from "@/test/utils";

import { api, ApiError, session } from "./client";

function headersOf(fetchMock: ReturnType<typeof mockApi>, call = 0) {
  return fetchMock.mock.calls[call][1]!.headers as Record<string, string>;
}

describe("api", () => {
  it("reads JSON with the session cookie and the viewer's zone", async () => {
    const fetchMock = mockApi({ "GET /api/me": { body: { id: 1 } } });
    await expect(api.get("/api/me")).resolves.toEqual({ id: 1 });

    const init = fetchMock.mock.calls[0][1]!;
    expect(init.credentials).toBe("same-origin");
    const headers = headersOf(fetchMock);
    expect(headers["X-Timezone"]).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
    // Reads don't carry the CSRF header; only mutations need it.
    expect(headers["X-Requested-With"]).toBeUndefined();
  });

  it("sends the CSRF header and a JSON body on every mutation", async () => {
    const fetchMock = mockApi({
      "POST /api/workspaces": ({ body }) => ({ status: 201, body }),
      "PATCH /api/workspaces/1": { body: {} },
      "DELETE /api/workspaces/1": { status: 204 },
    });
    await expect(
      api.post("/api/workspaces", { name: "Ours" }),
    ).resolves.toEqual({ name: "Ours" });
    await api.patch("/api/workspaces/1", { name: "Theirs" });
    await expect(api.delete("/api/workspaces/1")).resolves.toBeUndefined();

    for (const call of [0, 1, 2]) {
      expect(headersOf(fetchMock, call)["X-Requested-With"]).toBe(
        "sensibility",
      );
    }
    expect(headersOf(fetchMock)["Content-Type"]).toBe("application/json");
  });

  it("puts query parameters in the URL, skipping empty ones", async () => {
    const fetchMock = mockApi({ "GET /api/x": { body: {} } });
    await api.get("/api/x", {
      query: { per: "year", retired: false, no: null },
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/x?per=year&retired=false");
  });

  it("throws the server's {error} as an ApiError", async () => {
    mockApi({
      "POST /api/workspaces": {
        status: 400,
        body: { error: "Name is required" },
      },
    });
    const error = await api
      .post<never>("/api/workspaces", {})
      .catch((e: ApiError) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
    expect(error.message).toBe("Name is required");
  });

  it("names the status when the body has no error", async () => {
    mockApi({ "GET /api/x": { status: 502 } });
    await expect(api.get("/api/x")).rejects.toThrow("Request failed (502)");
  });

  it("goes to /login on a 401", async () => {
    const expired = vi.spyOn(session, "expired").mockImplementation(() => {});
    mockApi({
      "GET /api/me": { status: 401, body: { error: "Login required" } },
    });
    await expect(api.get("/api/me")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalled();
  });
});
