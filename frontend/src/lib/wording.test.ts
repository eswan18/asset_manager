import { describe, expect, it } from "vitest";

import { aRole, dayText, initials } from "./wording";

describe("initials", () => {
  it.each([
    ["Ethan Swan", "ES"],
    ["Ethan Patrick Swan", "ES"],
    ["ethan", "E"],
    ["jordan.swan@example.com", "JS"],
    ["me@example.com", "M"],
    ["", "?"],
    [null, "?"],
  ])("%s -> %s", (name, expected) => {
    expect(initials(name)).toBe(expected);
  });
});

describe("aRole", () => {
  it("takes the right article", () => {
    expect(aRole("owner")).toBe("an owner");
    expect(aRole("editor")).toBe("an editor");
    expect(aRole("viewer")).toBe("a viewer");
  });
});

describe("dayText", () => {
  it("is the day in the given zone", () => {
    // 03:00 UTC on Nov 4 is still Nov 3 in Chicago.
    expect(dayText("2026-11-04T03:00:00+00:00", "America/Chicago")).toBe(
      "Nov 3",
    );
    expect(dayText("2026-11-04T03:00:00+00:00", "Asia/Tokyo")).toBe("Nov 4");
  });
});
