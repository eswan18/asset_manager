import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { useCreateWorkspace } from "@/api/settings";
import {
  useAnswerInvite,
  useMe,
  useMyInvites,
  type MyInvite,
} from "@/api/shell";
import { useDocumentTitle } from "@/components/shell/workspace-context";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FormError, Input } from "@/components/ui/field";
import { flash } from "@/components/ui/toaster";
import { firstName, welcomeInviteLine } from "@/lib/settings";
import { cn } from "@/lib/utils";
import { aRole } from "@/lib/wording";

/**
 * `/welcome` (board W; welcome.html), outside any workspace: "Welcome,
 * {first name}" with no workspace, "New workspace" otherwise (the account
 * menu links here). Invites you can accept, with Join (into that
 * workspace) and Decline (stays here); then "Start your own workspace",
 * which goes into the new one. With no invites the invites card and the
 * "or" divider are left out, and Create is the primary button.
 */
export function WelcomePage() {
  const me = useMe();
  const invites = useMyInvites();
  const hasWorkspaces = (me.data?.workspaces.length ?? 0) > 0;
  useDocumentTitle(hasWorkspaces ? "New workspace" : "Welcome");
  // The shell has loaded `me`; wait for the invites so Create's button
  // doesn't change under you.
  if (!me.data || invites.isPending) return null;
  const acceptable = (invites.data ?? []).filter((i) => i.acceptable);

  return (
    <div className="fade-in mx-auto flex max-w-[640px] flex-col gap-4 pt-6 phone:pt-2">
      <div className="flex flex-col gap-1.5 px-1 pb-2">
        <h1 className="font-display text-[36px] leading-[1.2] font-semibold tracking-[-0.02em] [overflow-wrap:anywhere] phone:text-[30px]">
          {hasWorkspaces
            ? "New workspace"
            : `Welcome, ${firstName(me.data.name, me.data.email)}`}
        </h1>
        <span className="text-[16px] text-muted">
          A workspace holds a set of accounts and cash flows that you track,
          alone or with others.
        </span>
      </div>

      {acceptable.length > 0 && (
        <>
          <Invites invites={acceptable} />
          <div
            className={cn(
              "flex items-center gap-3 text-[14px] text-muted",
              "before:h-px before:grow before:bg-rule-strong before:content-['']",
              "after:h-px after:grow after:bg-rule-strong after:content-['']",
            )}
          >
            or
          </div>
        </>
      )}

      <Create primary={acceptable.length === 0} />
    </div>
  );
}

const card = "gap-0 phone:px-5 phone:py-6";
const h2 = "font-display text-[20px] font-semibold";

/** Invites for you: Decline and Join on each (on phones they share a row).
 * A refusal shows at the top of the card. */
function Invites({ invites }: { invites: MyInvite[] }) {
  const navigate = useNavigate();
  const { accept, decline, refreshInvites } = useAnswerInvite();
  const [error, setError] = useState<string>();
  const busy = accept.isPending || decline.isPending;
  const failed = (e: Error) => setError(e.message);

  const onJoin = (invite: MyInvite) => {
    setError(undefined);
    accept.mutateAsync(invite.id).then((joined) => {
      flash.success(
        `Joined ${invite.workspace_name} as ${aRole(joined.role)}.`,
      );
      navigate(`/workspaces/${joined.workspace_id}`);
      return refreshInvites();
    }, failed);
  };
  const onDecline = (invite: MyInvite) => {
    setError(undefined);
    decline.mutateAsync(invite.id).then(() => {
      flash.success(`Declined the invite to ${invite.workspace_name}.`);
      return refreshInvites();
    }, failed);
  };

  const button = "phone:w-full phone:flex-[1_1_0]";
  return (
    <Card className={card} aria-label="Invites for you">
      <h2 className={cn(h2, "border-b border-rule-strong pb-3")}>
        Invites for you
      </h2>
      {error && <FormError className="mt-3">{error}</FormError>}
      {invites.map((invite) => (
        <div
          key={invite.id}
          className="flex flex-wrap items-center justify-between gap-3 border-b border-rule py-4 last:border-b-0 last:pb-0"
        >
          <span className="flex min-w-0 flex-col gap-0.5">
            <strong className="font-display text-[18px] font-semibold [overflow-wrap:anywhere]">
              {invite.workspace_name}
            </strong>
            <span className="text-[14px] text-muted">
              {welcomeInviteLine(invite)}
            </span>
          </span>
          <span className="flex gap-2 phone:basis-full">
            <Button
              variant="outline"
              size="lg"
              disabled={busy}
              aria-label={`Decline the invite to ${invite.workspace_name}`}
              onClick={() => onDecline(invite)}
              className={button}
            >
              Decline
            </Button>
            <Button
              variant="primary"
              size="lg"
              disabled={busy}
              aria-label={`Join ${invite.workspace_name}`}
              onClick={() => onJoin(invite)}
              className={button}
            >
              Join
            </Button>
          </span>
        </div>
      ))}
    </Card>
  );
}

/** Start your own workspace, then go into it. A refusal keeps the name. */
function Create({ primary }: { primary: boolean }) {
  const navigate = useNavigate();
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (error) field.current?.focus();
  }, [error]);

  return (
    <Card className={cn(card, "gap-4")}>
      <h2 className={h2}>Start your own workspace</h2>
      <form
        className="flex flex-wrap items-end gap-2.5"
        onSubmit={(event) => {
          event.preventDefault();
          setError(undefined);
          create.mutateAsync(name).then(
            (created) => {
              flash.success(`Created ${created.name}.`);
              navigate(`/workspaces/${created.id}`);
            },
            (e: Error) => setError(e.message),
          );
        }}
      >
        {error && <FormError className="basis-full">{error}</FormError>}
        <Field label="Name" className="flex-[1_1_220px] phone:basis-full">
          <Input
            ref={field}
            type="text"
            name="name"
            placeholder="e.g. Personal"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={error ? true : undefined}
            className="aria-invalid:border-danger"
          />
        </Field>
        <Button
          type="submit"
          variant={primary ? "primary" : "primary-outline"}
          size="lg"
          disabled={create.isPending}
          className="phone:basis-full"
        >
          Create workspace
        </Button>
      </form>
    </Card>
  );
}
