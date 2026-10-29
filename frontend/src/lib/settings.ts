/** The settings and welcome pages' wording (web/settings_routes.py's
 * settings_view and web/welcome_routes.py, in TypeScript). Pure. */
import { aRole, dayText, type Role } from "./wording";

/** "Owner", "Editor", "Viewer". */
export function roleLabel(role: Role): string {
  return role[0].toUpperCase() + role.slice(1);
}

/** "1 member", "3 members". */
export function memberCount(count: number): string {
  return `${count} member${count === 1 ? "" : "s"}`;
}

/** Who deleting reaches: "you, its only member" or "all 3 members". */
export function deleteReach(count: number): string {
  return count === 1 ? "you, its only member" : `all ${count} members`;
}

/** "You're an owner of this workspace." */
export function yourRole(role: Role): string {
  return `You're ${aRole(role)} of this workspace.`;
}

/** A pending invite's line under its email: "Sent by you Oct 20 · expires
 * Nov 3", or, once its sender is no longer an owner, "Sent by Sam Oct 20 ·
 * lapsed: Sam is no longer an owner". Days are in `zone` (default: the
 * viewer's). */
export function inviteLine(
  invite: {
    sent_by_you: boolean;
    sender_name: string | null;
    created_at: string;
    expires_at: string;
    lapsed: boolean;
  },
  zone?: string,
): string {
  const sentBy = invite.sent_by_you
    ? "you"
    : (invite.sender_name ?? "a former member");
  const sent = `Sent by ${sentBy} ${dayText(invite.created_at, zone)} · `;
  return invite.lapsed
    ? `${sent}lapsed: ${sentBy} is no longer an owner`
    : `${sent}expires ${dayText(invite.expires_at, zone)}`;
}

/** The welcome page's greeting name: "Sam" from "Sam Lee", the email's
 * local part without a name. */
export function firstName(name: string | null, email: string): string {
  const trimmed = (name ?? "").trim();
  return trimmed ? trimmed.split(/\s+/)[0] : email.split("@")[0];
}

/** A welcome-page invite's line: "Jordan Swan invited you as an editor ·
 * expires Nov 3". */
export function welcomeInviteLine(
  invite: { sender_name: string; role: Role; expires_at: string },
  zone?: string,
): string {
  return (
    `${invite.sender_name} invited you as ${aRole(invite.role)} · ` +
    `expires ${dayText(invite.expires_at, zone)}`
  );
}
