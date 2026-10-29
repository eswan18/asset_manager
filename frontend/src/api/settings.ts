/** The settings and welcome pages: a workspace's people and invites, and the
 * writes both pages make (web/api_settings.py reads; web/api_routes.py
 * writes). Your own invites, Join and Decline are the shell's
 * (`useMyInvites`, `useAnswerInvite` in api/shell.ts). */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type { Role } from "@/lib/wording";

import { api } from "./client";
import { queryKeys } from "./queryKeys";
import { getMe, type Me } from "./shell";

/** A member, oldest first. `removable`: you may remove them (on your own
 * row: leave). Owners remove anyone; anyone removes themselves, except the
 * last owner. */
export interface SettingsMember {
  user_id: number;
  name: string | null;
  email: string;
  /** The name, or the email without one. */
  display_name: string;
  role: Role;
  joined_at: string;
  you: boolean;
  removable: boolean;
}

/** A pending invite (owners only). `sender_name` is null once the sender
 * is no longer a member; `lapsed` once they are no longer an owner, so it
 * cannot be accepted. */
export interface SettingsInvite {
  id: number;
  email: string;
  role: Role;
  invited_by: number;
  sent_by_you: boolean;
  sender_name: string | null;
  created_at: string;
  expires_at: string;
  lapsed: boolean;
}

/** `GET /api/workspaces/{id}/settings`. */
export interface WorkspaceSettings {
  id: number;
  name: string;
  /** Your role here. */
  role: Role;
  is_owner: boolean;
  /** False only for the last owner. */
  can_leave: boolean;
  members: SettingsMember[];
  /** Pending, oldest first; empty unless you're an owner. */
  invites: SettingsInvite[];
  invite_ttl_days: number;
  /** The role choices, in order. */
  roles: Role[];
}

export interface WorkspaceOut {
  id: number;
  name: string;
  role: Role;
}

export interface InviteOut {
  id: number;
  workspace_id: number;
  email: string;
  role: Role;
}

const ws = (workspaceId: number) => `/api/workspaces/${workspaceId}`;

export const getSettings = (workspaceId: number) =>
  api.get<WorkspaceSettings>(`${ws(workspaceId)}/settings`);

export const createWorkspace = (name: string) =>
  api.post<WorkspaceOut>("/api/workspaces", { name });

export const renameWorkspace = (workspaceId: number, name: string) =>
  api.patch<WorkspaceOut>(ws(workspaceId), { name });

export const deleteWorkspace = (workspaceId: number) =>
  api.delete<unknown>(ws(workspaceId));

export const changeRole = (workspaceId: number, userId: number, role: Role) =>
  api.patch<{ user_id: number; role: Role }>(
    `${ws(workspaceId)}/members/${userId}`,
    { role },
  );

/** Remove a member, or (your own id) leave. */
export const removeMember = (workspaceId: number, userId: number) =>
  api.delete<unknown>(`${ws(workspaceId)}/members/${userId}`);

export const createInvite = (workspaceId: number, email: string, role: Role) =>
  api.post<InviteOut>(`${ws(workspaceId)}/invites`, { email, role });

export const revokeInvite = (workspaceId: number, inviteId: number) =>
  api.delete<unknown>(`${ws(workspaceId)}/invites/${inviteId}`);

/** The settings page's query: what `useWorkspaceSettings` reads and the
 * gear prefetches (api/prefetch.ts). */
export const settingsQuery = (workspaceId: number) =>
  queryOptions({
    queryKey: queryKeys.settings(workspaceId),
    queryFn: () => getSettings(workspaceId),
  });

export function useWorkspaceSettings(workspaceId: number) {
  return useQuery(settingsQuery(workspaceId));
}

/**
 * Every write the settings page makes. Each resolves once what it changed
 * is refetched:
 * - rename and role changes touch `me` (the picker's name, your role) and
 *   the workspace;
 * - removing someone, inviting and revoking touch only this page;
 * - leaving and deleting resolve with a fresh `me` without storing it: the
 *   caller navigates out of the workspace (`homeOf`) and then calls
 *   `settleGone(me)` in the same tick, so the shell never renders this
 *   workspace's URL with a `me` that no longer has it (a not-found page).
 */
export function useSettingsMutations(workspaceId: number) {
  const queryClient = useQueryClient();
  const refresh = (queryKey: readonly unknown[]) =>
    queryClient.invalidateQueries({ queryKey });
  const thenRefresh =
    <A extends unknown[], T>(
      write: (...args: A) => Promise<T>,
      ...keys: (readonly unknown[])[]
    ) =>
    async (...args: A) => {
      const result = await write(...args);
      await Promise.all(keys.map(refresh));
      return result;
    };
  const me = queryKeys.me();
  const workspace = queryKeys.workspace(workspaceId);
  const settings = queryKeys.settings(workspaceId);

  return {
    rename: useMutation({
      mutationFn: thenRefresh(
        (name: string) => renameWorkspace(workspaceId, name),
        me,
        workspace,
      ),
    }),
    changeRole: useMutation({
      mutationFn: thenRefresh(
        ({ userId, role }: { userId: number; role: Role }) =>
          changeRole(workspaceId, userId, role),
        me,
        workspace,
      ),
    }),
    remove: useMutation({
      mutationFn: thenRefresh(
        (userId: number) => removeMember(workspaceId, userId),
        settings,
        queryKeys.members(workspaceId),
      ),
    }),
    leave: useMutation({
      mutationFn: async (userId: number) => {
        await removeMember(workspaceId, userId);
        return getMe();
      },
    }),
    destroy: useMutation({
      mutationFn: async () => {
        await deleteWorkspace(workspaceId);
        return getMe();
      },
    }),
    invite: useMutation({
      mutationFn: thenRefresh(
        ({ email, role }: { email: string; role: Role }) =>
          createInvite(workspaceId, email, role),
        settings,
        queryKeys.workspaceInvites(workspaceId),
      ),
    }),
    revoke: useMutation({
      mutationFn: thenRefresh(
        (inviteId: number) => revokeInvite(workspaceId, inviteId),
        settings,
        queryKeys.workspaceInvites(workspaceId),
      ),
    }),
    /** After leaving or deleting: store the fresh `me` and drop the
     * workspace's queries (refetching them would only 404). */
    settleGone: (fresh: Me) => {
      queryClient.setQueryData(me, fresh);
      queryClient.removeQueries({ queryKey: workspace });
    },
  };
}

/** Where leaving or deleting lands, as `GET /` would send you: your oldest
 * remaining workspace, else the welcome page. */
export function homeOf(me: Me): string {
  const oldest = me.workspaces[0];
  return oldest ? `/workspaces/${oldest.id}` : "/welcome";
}

/** Create a workspace (welcome). Resolves once `me` lists it, so navigating
 * into it works. */
export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const created = await createWorkspace(name);
      await queryClient.invalidateQueries({ queryKey: queryKeys.me() });
      return created;
    },
  });
}
