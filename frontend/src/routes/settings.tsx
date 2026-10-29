import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import {
  homeOf,
  useSettingsMutations,
  useWorkspaceSettings,
  type SettingsInvite,
  type SettingsMember,
  type WorkspaceSettings,
} from "@/api/settings";
import type { Me } from "@/api/shell";
import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Field, FormError, Input, Select } from "@/components/ui/field";
import { Tag } from "@/components/ui/tag";
import { flash } from "@/components/ui/toaster";
import {
  deleteReach,
  inviteLine,
  memberCount,
  roleLabel,
  yourRole,
} from "@/lib/settings";
import { cn } from "@/lib/utils";
import { aRole, initials, type Role } from "@/lib/wording";

/**
 * `/workspaces/:workspaceId/settings` (board V; settings.html). Two columns
 * that stack under 860px: General and Leave / Delete on the left, People on
 * the right. Owners get every control; editors and viewers get the page
 * read-only plus Leave.
 *
 * Removing, revoking, leaving and deleting ask first, in the page, through
 * `?confirm=member-{id}|invite-{id}|leave|delete` as the Jinja page does
 * (ignored when you could not act on it); Keep goes back to the bare page.
 * A refusal shows the server's message beside the control it came from and
 * closes any confirm. Choosing a role saves it.
 */
export function SettingsPage() {
  const workspace = useWorkspace();
  useDocumentTitle(`Settings · ${workspace.name}`);
  const settings = useWorkspaceSettings(workspace.id);
  if (settings.isPending) return null;
  if (settings.isError) {
    return (
      <FormError>
        Couldn't load the settings ({settings.error.message}). Try reloading the
        page.
      </FormError>
    );
  }
  // Keyed: another workspace's settings start with no errors or drafts.
  return <Settings key={workspace.id} settings={settings.data} />;
}

/** Where a refusal shows: the section whose control it came from. */
interface Errors {
  general?: string;
  leave?: string;
  people?: string;
  invite?: string;
}

const h2 = "font-display text-[20px] font-semibold";
const why = "text-[14px] text-muted";

function Settings({ settings }: { settings: WorkspaceSettings }) {
  const workspace = useWorkspace();
  const path = `${workspace.base}/settings`;
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const confirm = params.get("confirm") ?? "";
  const writes = useSettingsMutations(workspace.id);
  const [errors, setErrors] = useState<Errors>({});

  const { name, is_owner: isOwner, can_leave: canLeave } = settings;
  const me = settings.members.find((m) => m.you);
  const count = settings.members.length;

  /** Every link within the page starts afresh, as the Jinja page's
   * navigations do. */
  const clear = () => setErrors({});
  /** A write answered: close any confirm, as the Jinja page's redirect back
   * (or its re-render at the POST's path) does. */
  const closeConfirm = () => {
    if (confirm) navigate(path);
  };
  const succeeded = (text: string) => {
    flash.success(text);
    closeConfirm();
  };
  const refused = (section: keyof Errors) => (error: Error) => {
    setErrors({ [section]: error.message });
    closeConfirm();
  };
  /** Leaving and deleting land where `GET /` would. */
  const gone = (text: string) => (fresh: Me) => {
    flash.success(text);
    navigate(homeOf(fresh));
    writes.settleGone(fresh);
  };

  const leave = () => {
    if (!me) return;
    clear();
    writes.leave
      .mutateAsync(me.user_id)
      .then(gone(`You left ${name}.`), refused("leave"));
  };

  // In Leave / Delete a confirm's why is 14px, as the card's other lines
  // (settings.html's `.outline-item .why`); in the People list it is not.
  const leaveConfirm = (inOutline: boolean) => (
    <Confirm
      inOutline={inOutline}
      title={`Leave ${name}?`}
      why="You'll lose access right away."
      action="Leave workspace"
      onConfirm={leave}
      busy={writes.leave.isPending}
      keepTo={path}
      onKeep={clear}
    />
  );

  return (
    <>
      <div className="fade-in mb-4 flex flex-col gap-1 px-1 pt-2 pb-1">
        <h1 className="font-display text-[32px] leading-[1.2] font-semibold tracking-[-0.02em] [overflow-wrap:anywhere]">
          {name} settings
        </h1>
        <span className="text-muted">{yourRole(settings.role)}</span>
      </div>

      <div className="fade-in grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-start gap-4 [animation-delay:0.05s] [@media(max-width:860px)]:grid-cols-[minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          {isOwner && (
            <General
              name={name}
              error={errors.general}
              busy={writes.rename.isPending}
              onSave={(text) => {
                clear();
                return writes.rename.mutateAsync(text).then((saved) => {
                  succeeded(`Saved ${saved.name}.`);
                  return true;
                }, refused("general"));
              }}
            />
          )}

          <section
            aria-label="Leave or delete"
            className="flex flex-col gap-4 rounded-card px-7 py-6 shadow-[inset_0_0_0_1px_var(--rule-strong)] phone:px-4 phone:py-5"
          >
            <div className="flex flex-col items-start gap-2">
              <strong className="font-semibold">Leave {name}</strong>
              {errors.leave && <FormError>{errors.leave}</FormError>}
              {!canLeave ? (
                <span className={why}>
                  You're its only owner, so you can't leave. Make someone else
                  an owner first, or delete the workspace.
                </span>
              ) : confirm === "leave" ? (
                <div className="self-stretch">{leaveConfirm(true)}</div>
              ) : (
                <>
                  <span className={why}>
                    {isOwner
                      ? "You'll lose access. Another owner stays, so you can leave."
                      : "You'll lose access until an owner invites you again."}
                  </span>
                  <Button asChild variant="outline">
                    <Link to={`${path}?confirm=leave`} onClick={clear}>
                      Leave
                    </Link>
                  </Button>
                </>
              )}
            </div>
            {isOwner && (
              <div className="flex flex-col items-start gap-2 border-t border-rule-strong pt-4">
                <strong className="font-semibold">Delete {name}</strong>
                {confirm === "delete" ? (
                  <Confirm
                    inOutline
                    className="self-stretch"
                    title={`Delete ${name} for ${deleteReach(count)}?`}
                    why="Its data is kept and can be restored by an admin."
                    action="Delete workspace"
                    busy={writes.destroy.isPending}
                    onConfirm={() => {
                      clear();
                      writes.destroy
                        .mutateAsync()
                        .then(gone(`Deleted ${name}.`), (error: Error) =>
                          flash.error(error.message),
                        );
                    }}
                    keepTo={path}
                    onKeep={clear}
                  />
                ) : (
                  <>
                    <span className={why}>
                      Removes it for {deleteReach(count)}. Its data is kept and
                      can be restored by an admin.
                    </span>
                    <Button asChild variant="danger-outline">
                      <Link to={`${path}?confirm=delete`} onClick={clear}>
                        Delete workspace
                      </Link>
                    </Button>
                  </>
                )}
              </div>
            )}
          </section>
        </div>

        <Card className="phone:px-4 phone:py-5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-rule-strong pb-3">
            <h2 className={h2}>People</h2>
            <span className="text-[14px] text-muted">
              {memberCount(count)}
              {settings.invites.length > 0 &&
                ` · ${settings.invites.length} invited`}
            </span>
          </div>

          {isOwner && (
            <InviteForm
              roles={settings.roles}
              error={errors.invite}
              busy={writes.invite.isPending}
              onInvite={(email, role) => {
                clear();
                return writes.invite
                  .mutateAsync({ email, role })
                  .then((sent) => {
                    succeeded(`Invited ${sent.email} as ${aRole(sent.role)}.`);
                    return true;
                  }, refused("invite"));
              }}
            />
          )}

          {errors.people && (
            <FormError className="mt-3">{errors.people}</FormError>
          )}

          <ul className="list-none">
            {settings.members.map((member) => {
              const confirming =
                member.removable && confirm === `member-${member.user_id}`;
              if (confirming && member.you) {
                return (
                  <li key={`m${member.user_id}`}>{leaveConfirm(false)}</li>
                );
              }
              if (confirming) {
                return (
                  <Confirm
                    key={`m${member.user_id}`}
                    as="li"
                    className="my-2"
                    title={`Remove ${member.display_name}?`}
                    why={`They lose access to ${name} right away. You can invite them again.`}
                    action="Remove"
                    busy={writes.remove.isPending}
                    onConfirm={() => {
                      clear();
                      writes.remove
                        .mutateAsync(member.user_id)
                        .then(
                          () => succeeded(`Removed ${member.display_name}.`),
                          refused("people"),
                        );
                    }}
                    keepTo={path}
                    onKeep={clear}
                  />
                );
              }
              return (
                <MemberRow
                  key={`m${member.user_id}`}
                  member={member}
                  workspaceName={name}
                  isOwner={isOwner}
                  roles={settings.roles}
                  removeTo={`${path}?confirm=member-${member.user_id}`}
                  onRemove={clear}
                  onRole={(role) => {
                    clear();
                    return writes.changeRole
                      .mutateAsync({ userId: member.user_id, role })
                      .then(
                        () =>
                          flash.success(
                            member.you
                              ? `You're now ${aRole(role)}.`
                              : `${member.display_name} is now ${aRole(role)}.`,
                          ),
                        refused("people"),
                      );
                  }}
                />
              );
            })}
            {settings.invites.map((invite) =>
              confirm === `invite-${invite.id}` ? (
                <Confirm
                  key={`i${invite.id}`}
                  as="li"
                  className="my-2"
                  title={`Revoke the invite to ${invite.email}?`}
                  why="They won't be able to join with it."
                  action="Revoke invite"
                  busy={writes.revoke.isPending}
                  onConfirm={() => {
                    clear();
                    writes.revoke
                      .mutateAsync(invite.id)
                      .then(
                        () =>
                          succeeded(`Revoked the invite to ${invite.email}.`),
                        refused("people"),
                      );
                  }}
                  keepTo={path}
                  onKeep={clear}
                />
              ) : (
                <InviteRow
                  key={`i${invite.id}`}
                  invite={invite}
                  revokeTo={`${path}?confirm=invite-${invite.id}`}
                  onRevoke={clear}
                />
              ),
            )}
          </ul>

          <p className="pt-3 text-[13px] text-muted">
            {isOwner &&
              "No email is sent: tell them yourself, and they'll see the " +
                "invite when they log in with that address. Invites expire " +
                `after ${settings.invite_ttl_days} days. `}
            Viewers look; editors also change data; owners also manage the
            workspace and its people.
            {!isOwner && " Only owners can invite people or change roles."}
          </p>
        </Card>
      </div>
    </>
  );
}

/** Focus `ref` whenever `when` turns truthy (a refused form's field, as the
 * Jinja page's `autofocus` on its re-render). */
function useFocusWhen(ref: RefObject<HTMLElement | null>, when: unknown) {
  useEffect(() => {
    if (when) ref.current?.focus();
  }, [ref, when]);
}

/** General: the workspace's name. A refusal keeps what was typed. */
function General({
  name,
  error,
  busy,
  onSave,
}: {
  name: string;
  error?: string;
  busy: boolean;
  /** Resolves true once saved. */
  onSave: (name: string) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  useFocusWhen(field, error);
  return (
    <Card className="gap-4 phone:px-4 phone:py-5">
      <CardTitle>General</CardTitle>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(draft ?? name).then((saved) => {
            if (saved === true) setDraft(null);
          });
        }}
      >
        {error && <FormError>{error}</FormError>}
        <Field label="Name">
          <Input
            ref={field}
            type="text"
            name="name"
            required
            value={draft ?? name}
            onChange={(event) => setDraft(event.target.value)}
            aria-invalid={error ? true : undefined}
            className="aria-invalid:border-danger"
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={busy}
          className="self-end"
        >
          Save
        </Button>
      </form>
    </Card>
  );
}

/** Invite by email with a role. A refusal keeps both. */
function InviteForm({
  roles,
  error,
  busy,
  onInvite,
}: {
  roles: Role[];
  error?: string;
  busy: boolean;
  /** Resolves true once sent. */
  onInvite: (email: string, role: Role) => Promise<unknown>;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const field = useRef<HTMLInputElement>(null);
  useFocusWhen(field, error);
  return (
    <form
      aria-label="Invite"
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_120px_auto] items-center gap-2 border-b border-rule py-4",
        "phone:grid-cols-[minmax(0,1fr)_auto]",
      )}
      onSubmit={(event) => {
        event.preventDefault();
        onInvite(email, role).then((sent) => {
          if (sent !== true) return;
          setEmail("");
          setRole("editor");
        });
      }}
    >
      {error && <FormError className="col-span-full">{error}</FormError>}
      <Input
        ref={field}
        type="email"
        name="email"
        placeholder="Invite by email"
        aria-label="Invite by email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        aria-invalid={error ? true : undefined}
        className="aria-invalid:border-danger phone:col-span-full"
      />
      <Select
        name="role"
        aria-label="Role"
        value={role}
        onChange={(event) => setRole(event.target.value as Role)}
        className="px-2.5"
      >
        {roles.map((r) => (
          <option key={r} value={r}>
            {roleLabel(r)}
          </option>
        ))}
      </Select>
      <Button type="submit" variant="primary" size="lg" disabled={busy}>
        Invite
      </Button>
    </form>
  );
}

/** A person's row: avatar, name and email, role (a select for owners), and
 * × to remove (on your own row: leave). On phones the role and × sit
 * together under the name and email. */
const personRow = cn(
  "grid min-h-[68px] grid-cols-[40px_minmax(0,1fr)_auto_44px] items-center gap-3 border-b border-rule py-1.5",
  "phone:grid-cols-[40px_auto_44px_minmax(0,1fr)] phone:gap-x-3 phone:gap-y-2 phone:py-3",
);
const avatar =
  "flex size-10 items-center justify-center rounded-full text-[13px] font-semibold phone:self-start";
const personMain = "flex min-w-0 flex-col gap-0.5 phone:col-[2/-1]";
const personName =
  "flex flex-wrap items-center gap-x-2 gap-y-1 font-medium [overflow-wrap:anywhere]";
const personSub =
  "text-[13px] text-muted phone:whitespace-normal phone:[overflow-wrap:anywhere]";
const personRole = "text-[14px] text-muted px-2.5 phone:px-0";
const underMain = "phone:col-start-2 phone:row-start-2";
const besideRole = "phone:col-start-3 phone:row-start-2";

function MemberRow({
  member,
  workspaceName,
  isOwner,
  roles,
  removeTo,
  onRemove,
  onRole,
}: {
  member: SettingsMember;
  workspaceName: string;
  isOwner: boolean;
  roles: Role[];
  removeTo: string;
  onRemove: () => void;
  onRole: (role: Role) => Promise<unknown>;
}) {
  // The role being saved shows while it saves; a refusal puts the saved
  // one back.
  const [saving, setSaving] = useState<Role | null>(null);
  const label = member.you
    ? `Leave ${workspaceName}`
    : `Remove ${member.display_name}`;
  return (
    <li className={personRow}>
      <span className={cn(avatar, "bg-chip")} aria-hidden="true">
        {initials(member.display_name)}
      </span>
      <span className={personMain}>
        <span className={personName}>
          {member.display_name}
          {member.you && <span className="font-normal text-muted">(you)</span>}
        </span>
        <span className={cn(personSub, "truncate")}>{member.email}</span>
      </span>
      {isOwner ? (
        <Select
          name="role"
          aria-label={`Role for ${member.display_name}`}
          value={saving ?? member.role}
          disabled={saving !== null}
          onChange={(event) => {
            const role = event.target.value as Role;
            setSaving(role);
            onRole(role).finally(() => setSaving(null));
          }}
          className={cn(
            "min-h-10 w-auto px-2.5 text-[14px] phone:min-h-11",
            underMain,
          )}
        >
          {roles.map((r) => (
            <option key={r} value={r}>
              {roleLabel(r)}
            </option>
          ))}
        </Select>
      ) : (
        <span className={cn(personRole, underMain)}>
          {roleLabel(member.role)}
        </span>
      )}
      {member.removable ? (
        <RemoveLink to={removeTo} label={label} onClick={onRemove} />
      ) : (
        <span className={besideRole} />
      )}
    </li>
  );
}

function InviteRow({
  invite,
  revokeTo,
  onRevoke,
}: {
  invite: SettingsInvite;
  revokeTo: string;
  onRevoke: () => void;
}) {
  return (
    <li className={personRow}>
      <span
        className={cn(
          avatar,
          "border border-dashed border-rule-strong bg-transparent text-muted",
        )}
        aria-hidden="true"
      >
        {initials(invite.email)}
      </span>
      <span className={personMain}>
        <span className={personName}>
          {invite.email} <Tag estimate>Invited</Tag>
        </span>
        <span className={personSub}>{inviteLine(invite)}</span>
      </span>
      <span className={cn(personRole, underMain)}>
        {roleLabel(invite.role)}
      </span>
      <RemoveLink
        to={revokeTo}
        label={`Revoke the invite to ${invite.email}`}
        onClick={onRevoke}
      />
    </li>
  );
}

/** The × that asks first (`?confirm=`). */
function RemoveLink({
  to,
  label,
  onClick,
}: {
  to: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "flex size-11 items-center justify-center rounded-full text-muted hover:text-danger",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
        besideRole,
      )}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
      </svg>
    </Link>
  );
}

/** An inline "are you sure?" in place of a row or a section (base.html's
 * .confirm): the question, why, then Keep (focused, back to the bare page)
 * and the action. On phones the two buttons share a row, growing equally,
 * and stack only when they cannot fit. */
function Confirm({
  as: As = "div",
  className,
  inOutline = false,
  title,
  why: reason,
  action,
  onConfirm,
  busy,
  keepTo,
  onKeep,
}: {
  as?: "div" | "li";
  className?: string;
  inOutline?: boolean;
  title: string;
  why: ReactNode;
  action: string;
  onConfirm: () => void;
  busy: boolean;
  keepTo: string;
  onKeep: () => void;
}) {
  const keep = useRef<HTMLAnchorElement>(null);
  useEffect(() => keep.current?.focus(), []);
  const button = "phone:flex-auto phone:px-4 phone:whitespace-nowrap";
  return (
    <As
      data-slot="confirm"
      className={cn(
        "flex flex-col gap-2.5 rounded-xl px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--danger)]",
        "phone:px-3",
        className,
      )}
    >
      <span className="phone:[overflow-wrap:anywhere]">
        <strong className="font-semibold">{title}</strong>{" "}
        <span className={cn("text-muted", inOutline && "text-[14px]")}>
          {reason}
        </span>
      </span>
      <div className="flex flex-wrap justify-end gap-2">
        <Button asChild variant="outline" className={button}>
          <Link ref={keep} to={keepTo} onClick={onKeep}>
            Keep
          </Link>
        </Button>
        <Button
          variant="danger-solid"
          disabled={busy}
          onClick={onConfirm}
          className={button}
        >
          {action}
        </Button>
      </div>
    </As>
  );
}
