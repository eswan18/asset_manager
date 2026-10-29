import { useNavigate } from "react-router";

import { useAnswerInvite, useMyInvites, type MyInvite } from "@/api/shell";
import { Button } from "@/components/ui/button";
import { flash } from "@/components/ui/toaster";
import { cn } from "@/lib/utils";
import { aRole, dayText } from "@/lib/wording";

import { EnvelopeIcon } from "./icons";

/** The invite strips (board Z): one per pending invite, newest first, on
 * every page inside a workspace. Join goes into that workspace; Decline
 * stays here. Both refresh the list. */
export function InviteStrips() {
  const invites = useMyInvites();
  const newestFirst = (invites.data ?? [])
    .filter((invite) => invite.acceptable)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return newestFirst.map((invite) => (
    <InviteStrip key={invite.id} invite={invite} />
  ));
}

function InviteStrip({ invite }: { invite: MyInvite }) {
  const navigate = useNavigate();
  const { accept, decline, refreshInvites } = useAnswerInvite();
  const name = invite.workspace_name;
  const busy = accept.isPending || decline.isPending;
  const failed = (error: Error) => flash.error(error.message);

  // Promises, not mutate()'s callbacks: refreshing the invites unmounts this
  // strip, and those callbacks would then never run.
  const onJoin = () =>
    accept.mutateAsync(invite.id).then((joined) => {
      flash.success(`Joined ${name} as ${aRole(joined.role)}.`);
      navigate(`/workspaces/${joined.workspace_id}`);
      return refreshInvites();
    }, failed);
  const onDecline = () =>
    decline.mutateAsync(invite.id).then(() => {
      flash.success(`Declined the invite to ${name}.`);
      return refreshInvites();
    }, failed);

  const phoneButton =
    "phone:w-full phone:px-3 phone:py-1.5 phone:text-center phone:leading-tight";

  return (
    <section
      aria-label={`Invite to ${name}`}
      className={cn(
        "mb-4 flex flex-wrap items-center justify-between gap-4 rounded-card bg-surface py-4 pr-5 pl-6 shadow-[inset_4px_0_0_var(--primary)]",
        "phone:flex-col phone:items-stretch phone:gap-3.5 phone:pr-4 phone:pl-5",
      )}
    >
      <span className="flex min-w-0 items-center gap-3.5 phone:items-start">
        <span className="flex h-10 flex-[0_0_40px] items-center justify-center rounded-full bg-asset-tint text-asset">
          <EnvelopeIcon />
        </span>
        <span className="flex min-w-0 flex-col gap-0.5 [overflow-wrap:anywhere]">
          <span>
            {invite.sender_name ? (
              <>
                <strong className="font-semibold">{invite.sender_name}</strong>{" "}
                invited you
              </>
            ) : (
              "You're invited"
            )}{" "}
            to <strong className="font-semibold">{name}</strong> as{" "}
            {aRole(invite.role)}.
          </span>
          <span className="text-[13px] text-muted">
            Expires {dayText(invite.expires_at)}
          </span>
        </span>
      </span>
      <span className="flex flex-wrap gap-2 phone:grid phone:grid-cols-2">
        <Button
          variant="outline"
          size="lg"
          disabled={busy}
          onClick={onDecline}
          className={phoneButton}
        >
          Decline
        </Button>
        <Button
          variant="primary"
          size="lg"
          disabled={busy}
          onClick={onJoin}
          className={phoneButton}
        >
          Join {name}
        </Button>
      </span>
    </section>
  );
}
