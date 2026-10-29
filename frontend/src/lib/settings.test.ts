import { describe, expect, it } from "vitest";

import {
  deleteReach,
  firstName,
  inviteLine,
  memberCount,
  roleLabel,
  welcomeInviteLine,
  yourRole,
} from "./settings";

// The vectors are tests/test_settings_page.py's and test_welcome_page.py's.

describe("counts", () => {
  it("says member or members", () => {
    expect(memberCount(1)).toBe("1 member");
    expect(memberCount(3)).toBe("3 members");
  });

  it("says who deleting reaches", () => {
    expect(deleteReach(1)).toBe("you, its only member");
    expect(deleteReach(3)).toBe("all 3 members");
  });
});

describe("roles", () => {
  it("capitalizes a role for a select or a row", () => {
    expect(roleLabel("owner")).toBe("Owner");
    expect(roleLabel("viewer")).toBe("Viewer");
  });

  it("says yours", () => {
    expect(yourRole("owner")).toBe("You're an owner of this workspace.");
    expect(yourRole("viewer")).toBe("You're a viewer of this workspace.");
  });
});

describe("inviteLine", () => {
  // 02:00 UTC on Oct 21 is still Oct 20 in Chicago.
  const invite = {
    sent_by_you: true,
    sender_name: "Me",
    created_at: "2026-10-21T02:00:00+00:00",
    expires_at: "2026-11-04T02:00:00+00:00",
    lapsed: false,
  };

  it("dates the days in the viewer's zone", () => {
    expect(inviteLine(invite, "America/Chicago")).toBe(
      "Sent by you Oct 20 · expires Nov 3",
    );
    expect(inviteLine(invite, "UTC")).toBe(
      "Sent by you Oct 21 · expires Nov 4",
    );
  });

  it("names another sender, or a former member", () => {
    expect(inviteLine({ ...invite, sent_by_you: false }, "UTC")).toBe(
      "Sent by Me Oct 21 · expires Nov 4",
    );
    expect(
      inviteLine({ ...invite, sent_by_you: false, sender_name: null }, "UTC"),
    ).toBe("Sent by a former member Oct 21 · expires Nov 4");
  });

  it("says why a lapsed invite cannot be accepted", () => {
    expect(
      inviteLine({ ...invite, sent_by_you: false, lapsed: true }, "UTC"),
    ).toBe("Sent by Me Oct 21 · lapsed: Me is no longer an owner");
  });
});

describe("firstName", () => {
  it.each([
    ["Sam Lee", "s@example.com", "Sam"],
    ["  Stranger ", "stranger@example.com", "Stranger"],
    [null, "sam.lee@example.com", "sam.lee"],
    ["  ", "sam.lee@example.com", "sam.lee"],
  ])("%s <%s> -> %s", (name, email, expected) => {
    expect(firstName(name, email)).toBe(expected);
  });
});

describe("welcomeInviteLine", () => {
  it("says who, the role and when it expires", () => {
    expect(
      welcomeInviteLine(
        {
          sender_name: "Jordan Swan",
          role: "viewer",
          expires_at: "2026-11-04T02:00:00+00:00",
        },
        "America/Chicago",
      ),
    ).toBe("Jordan Swan invited you as a viewer · expires Nov 3");
  });
});
