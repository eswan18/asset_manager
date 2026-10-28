import { createContext, useContext, useEffect } from "react";

import type { Role } from "@/lib/wording";

export const APP_NAME = "Sensibility";

/** The workspace the current page is in, from the shell. */
export interface CurrentWorkspace {
  id: number;
  name: string;
  role: Role;
  /** The router path of its pages: `/workspaces/1` (+ `/accounts`, …). */
  base: string;
  /** Editors and owners change data; viewers only read. */
  canEdit: boolean;
  /** Owners also manage the workspace and its members. */
  isOwner: boolean;
}

export const WorkspaceContext = createContext<CurrentWorkspace | null>(null);

export function currentWorkspace(
  id: number,
  name: string,
  role: Role,
): CurrentWorkspace {
  return {
    id,
    name,
    role,
    base: `/workspaces/${id}`,
    canEdit: role !== "viewer",
    isOwner: role === "owner",
  };
}

/** The current workspace. Only inside `/workspaces/:workspaceId/…` routes,
 * which the shell renders only once it knows you're a member. */
export function useWorkspace(): CurrentWorkspace {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) {
    throw new Error("useWorkspace() outside a workspace route");
  }
  return workspace;
}

/** Sets the tab's title to "{title} · Sensibility" while mounted. */
export function useDocumentTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}
