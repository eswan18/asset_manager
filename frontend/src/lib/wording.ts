/** Small pieces of text shared by the shell and pages (web/wording.py and
 * _components.html's initials, in TypeScript). Pure. */

export type Role = "owner" | "editor" | "viewer";

/** Up to two initials for the account menu: "Ethan Swan" -> "ES",
 * "jordan.swan@example.com" -> "JS". */
export function initials(nameOrEmail: string | null | undefined): string {
  const words = (nameOrEmail || "?")
    .split("@")[0]
    .replaceAll(".", " ")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/** "an owner", "an editor", "a viewer". */
export function aRole(role: Role): string {
  return ("aeiou".includes(role[0]) ? "an " : "a ") + role;
}

/** "Oct 20": the day `instant` (an ISO timestamp) falls on in `zone`
 * (default: the viewer's). */
export function dayText(instant: string | Date, zone?: string): string {
  const when = typeof instant === "string" ? new Date(instant) : instant;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: zone,
  }).format(when);
}
