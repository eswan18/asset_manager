/** What the shell needs: you, your workspaces, your pending invites. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Role } from "@/lib/wording";

import { api } from "./client";
import { queryKeys } from "./queryKeys";

export type { Role };

/** A workspace you're in, with your role there (`GET /api/me`). */
export interface WorkspaceSummary {
  id: number;
  name: string;
  role: Role;
}

/** `GET /api/me`. `workspaces` is oldest membership first. */
export interface Me {
  id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
  workspaces: WorkspaceSummary[];
}

/** One of `GET /api/invites`. `sender_name` is the inviting owner's name (or
 * email); `acceptable` is false once the invite has lapsed (its sender is no
 * longer an owner), and the strip and the welcome page show only acceptable
 * ones. */
export interface MyInvite {
  id: number;
  workspace_id: number;
  workspace_name: string;
  email: string;
  role: Role;
  invited_by: number;
  sender_name: string;
  acceptable: boolean;
  created_at: string;
  expires_at: string;
}

export interface AcceptedInvite {
  workspace_id: number;
  role: Role;
}

export const getMe = () => api.get<Me>("/api/me");

export const getMyInvites = () =>
  api.get<{ invites: MyInvite[] }>("/api/invites").then((r) => r.invites);

export const acceptInvite = (inviteId: number) =>
  api.post<AcceptedInvite>(`/api/invites/${inviteId}/accept`);

export const declineInvite = (inviteId: number) =>
  api.post<unknown>(`/api/invites/${inviteId}/decline`);

export function useMe() {
  return useQuery({ queryKey: queryKeys.me(), queryFn: getMe });
}

export function useMyInvites() {
  return useQuery({ queryKey: queryKeys.myInvites(), queryFn: getMyInvites });
}

/** Join or decline. `accept` resolves once `me` lists the new workspace, so
 * navigating into it works. Call `refreshInvites()` last, after acting on the
 * answer: the refetch removes the strip, and a component's per-call mutation
 * callbacks never run once it has unmounted (use the promise from
 * `mutateAsync`, which always settles). */
export function useAnswerInvite() {
  const queryClient = useQueryClient();
  return {
    accept: useMutation({
      mutationFn: async (inviteId: number) => {
        const joined = await acceptInvite(inviteId);
        await queryClient.invalidateQueries({ queryKey: queryKeys.me() });
        return joined;
      },
    }),
    decline: useMutation({ mutationFn: declineInvite }),
    refreshInvites: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.myInvites() }),
  };
}
