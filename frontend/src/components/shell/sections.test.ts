import { describe, expect, it } from "vitest";

import { sameSectionIn, sectionOf, tabOf } from "./sections";

describe("sectionOf", () => {
  const base = "/workspaces/1";
  it.each([
    ["/workspaces/1", ""],
    ["/workspaces/1/", ""],
    ["/workspaces/1/accounts", "accounts"],
    ["/workspaces/1/accounts/5/edit", "accounts"],
    ["/workspaces/1/cash-flow-categories", "cash-flow-categories"],
    ["/workspaces/1/settings", "settings"],
    ["/workspaces/12/accounts", ""],
    ["/welcome", ""],
  ])("%s -> %j", (path, section) => {
    expect(sectionOf(path, base)).toBe(section);
  });
});

describe("tabOf", () => {
  it("puts the categories drawer under Cash flows", () => {
    expect(tabOf("cash-flow-categories")).toBe("cash_flows");
    expect(tabOf("")).toBe("dashboard");
    expect(tabOf("nope")).toBeNull();
  });
});

describe("sameSectionIn", () => {
  it("keeps the section, not the rest", () => {
    expect(sameSectionIn(2, "accounts")).toBe("/workspaces/2/accounts");
    expect(sameSectionIn(2, "")).toBe("/workspaces/2");
  });
});
