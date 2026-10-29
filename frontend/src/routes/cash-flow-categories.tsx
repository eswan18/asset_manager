import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";

import {
  useCashFlowsOverview,
  useCashFlowsPeriod,
  useCategoryWrites,
  type CategoryRow,
} from "@/api/cash-flows";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  RouteSheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetError,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/sheet";
import { APP_NAME, useWorkspace } from "@/components/shell/workspace-context";
import { categoryMeta, deleteWhy, type Period } from "@/lib/cash-flows";
import { cn } from "@/lib/utils";

const FIELD = cn(
  "min-w-0 grow rounded-input border border-rule-strong bg-input text-[15px] text-ink",
  "phone:min-h-11 phone:text-[16px]",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
);

/**
 * `cash-flow-categories` (cash_flow_categories.html): the categories, in the
 * order of the cards and the bar. A rename saves when its field loses
 * focus, or on Enter (once); the arrows move a category one place; delete
 * asks first, in the row; a new one is added last, ready for the next.
 * What just happened shows in the footer, not as a flash (the page is
 * behind the scrim). `?add=1` (the page's "+ New category") starts in the
 * new-name field.
 */
export function CashFlowCategoriesDrawer() {
  const workspace = useWorkspace();
  const { period, pageHref } = useCashFlowsPeriod(workspace.base);
  const [params] = useSearchParams();
  const overview = useCashFlowsOverview(workspace.id, period);
  const writes = useCategoryWrites(workspace.id);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [confirm, setConfirm] = useState<number | null>(null);
  const [invalid, setInvalid] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const newField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = `Categories · ${workspace.name} · ${APP_NAME}`;
  }, [workspace.name]);

  if (!workspace.canEdit) return <Navigate to={pageHref} replace />;
  const view = overview.data;
  if (!view) return null;

  /** Run a write; say what happened in the footer, or why not up top. */
  async function attempt<T>(
    write: () => Promise<T>,
    done: (result: T) => string,
  ): Promise<boolean> {
    try {
      const result = await write();
      setError(null);
      setInvalid(null);
      setStatus(done(result));
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setStatus("");
      return false;
    }
  }

  async function rename(row: CategoryRow, name: string) {
    const ok = await attempt(
      () => writes.rename.mutateAsync({ id: row.id, name }),
      (saved) => `Saved ${saved.name}`,
    );
    if (!ok) setInvalid(row.id);
    return ok;
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    const ok = await attempt(
      () => writes.create.mutateAsync(newName),
      (created) => `Added ${created.name}`,
    );
    if (ok) setNewName("");
    newField.current?.focus();
  }

  const rows = view.categories;
  return (
    <RouteSheet closeTo={pageHref}>
      <SheetContent>
        <SheetHeader
          eyebrow="Cash flows"
          title="Categories"
          className="border-b border-rule-strong"
        />
        <SheetBody className="gap-0 pt-4 phone:pt-4">
          {error && <SheetError className="mb-3">{error}</SheetError>}
          <p className="mb-3 text-[14px] text-muted">
            Order here is the order of the cards and the bar. Renaming or
            reordering saves right away.
          </p>

          <ul>
            {rows.map((row, index) =>
              confirm === row.id ? (
                <ConfirmDelete
                  key={row.id}
                  row={row}
                  onKeep={() => setConfirm(null)}
                  onDelete={() =>
                    attempt(
                      () => writes.remove.mutateAsync(row.id),
                      () => `Deleted ${row.name}`,
                    ).then(() => setConfirm(null))
                  }
                  busy={writes.remove.isPending}
                />
              ) : (
                <CategoryItem
                  // A new name from the server starts the row afresh.
                  key={`${row.id}:${row.name}`}
                  row={row}
                  period={period}
                  first={index === 0}
                  last={index === rows.length - 1}
                  invalid={invalid === row.id}
                  onRename={(name) => rename(row, name)}
                  onMove={(direction) =>
                    attempt(
                      () => writes.move.mutateAsync({ id: row.id, direction }),
                      () => `Moved ${row.name} ${direction}`,
                    )
                  }
                  onDelete={() => setConfirm(row.id)}
                />
              ),
            )}
            {rows.length === 0 && (
              <li className="py-3 text-[14px] text-muted">
                No categories yet. Add one below; expenses in it get their own
                card.
              </li>
            )}
          </ul>

          <form data-slot="cat-add" className="mt-4 flex gap-2" onSubmit={add}>
            <input
              ref={newField}
              type="text"
              name="name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New category name"
              aria-label="New category name"
              required
              data-autofocus={params.get("add") ? "" : undefined}
              className={cn(
                FIELD,
                "min-h-11 border-dashed px-3 phone:flex-[1_1_0]",
              )}
            />
            <Button
              type="submit"
              variant="secondary"
              className="min-h-11 phone:flex-none phone:px-[18px]"
              disabled={writes.create.isPending}
            >
              + Add
            </Button>
          </form>
        </SheetBody>
        <SheetFooter>
          <span
            role="status"
            className="mr-auto self-center text-[14px] text-muted"
          >
            {status}
          </span>
          <SheetClose asChild>
            <Button variant="primary">Done</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </RouteSheet>
  );
}

function CategoryItem({
  row,
  period,
  first,
  last,
  invalid,
  onRename,
  onMove,
  onDelete,
}: {
  row: CategoryRow;
  period: Period;
  first: boolean;
  last: boolean;
  invalid: boolean;
  onRename: (name: string) => Promise<boolean>;
  onMove: (direction: "up" | "down") => void;
  onDelete: () => void;
}) {
  const [value, setValue] = useState(row.name);
  const form = useRef<HTMLFormElement>(null);
  const field = useRef<HTMLInputElement>(null);
  // A rename submits once: Enter submits, and then losing focus would too.
  const sent = useRef(false);

  // A refused rename keeps its text, marked, with focus back in it.
  useEffect(() => {
    if (invalid) field.current?.focus();
  }, [invalid]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sent.current) return;
    sent.current = true;
    // On success the row starts afresh under its new name.
    if (!(await onRename(value))) sent.current = false;
  }

  return (
    <li
      data-slot="cat-row"
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 border-b border-rule py-2.5 phone:gap-1.5"
    >
      {/* Each arrow is a 44px square target around a small 40×26 chip; the
          up chip sits at the bottom of its target and the down chip at the
          top, so the pair reads as two chips 2px apart while the targets
          reach into the row's padding. */}
      <div data-slot="cat-move" className="-my-2.5 flex flex-col">
        {(["up", "down"] as const).map((direction) => (
          <button
            key={direction}
            type="button"
            aria-label={`Move ${row.name} ${direction}`}
            disabled={direction === "up" ? first : last}
            onClick={() => onMove(direction)}
            className={cn(
              "group flex size-11 cursor-pointer justify-center border-0 bg-transparent p-0 text-ink outline-none",
              "disabled:cursor-default disabled:opacity-35",
              direction === "up" ? "items-end pb-px" : "items-start pt-px",
            )}
          >
            <span className="flex h-[26px] w-10 items-center justify-center rounded-md bg-chip group-focus-visible:outline-2 group-focus-visible:outline-offset-1 group-focus-visible:outline-asset">
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <path
                  d={
                    direction === "up"
                      ? "M2.5 7.5L6 4l3.5 3.5"
                      : "M2.5 4.5L6 8l3.5-3.5"
                  }
                />
              </svg>
            </span>
          </button>
        ))}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <form
          ref={form}
          data-slot="cat-rename"
          className="flex items-center gap-2"
          onSubmit={submit}
        >
          <span
            aria-hidden="true"
            className="size-2.5 flex-none rounded-[3px]"
            style={{ background: row.color }}
          />
          <input
            ref={field}
            type="text"
            name="name"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            // A rename saves when its field loses focus, as Enter does.
            onBlur={() => {
              if (value.trim() !== row.name && !sent.current) {
                form.current?.requestSubmit();
              }
            }}
            aria-label={`Name of ${row.name}`}
            aria-invalid={invalid || undefined}
            required
            className={cn(FIELD, "min-h-10 px-2.5 aria-invalid:border-danger")}
          />
        </form>
        <span className="pl-[18px] text-[13px] text-muted phone:text-[12px]">
          {categoryMeta(
            {
              count: row.flow_count,
              expenses: row.expenses,
              income: row.income,
            },
            period,
          )}
        </span>
      </div>
      <button
        type="button"
        aria-label={`Delete ${row.name}`}
        onClick={onDelete}
        className="flex size-11 cursor-pointer items-center justify-center rounded-full bg-transparent text-muted hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          aria-hidden="true"
        >
          <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5" />
        </svg>
      </button>
    </li>
  );
}

/** Delete asks first, in the row's place: its flows become Uncategorized. */
function ConfirmDelete({
  row,
  onKeep,
  onDelete,
  busy,
}: {
  row: CategoryRow;
  onKeep: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => keep.current?.focus(), []);
  return (
    <li
      data-slot="cat-confirm"
      className="my-2 flex flex-col gap-2.5 rounded-xl px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--danger)] phone:p-3.5"
    >
      <span>
        <strong className="font-semibold">Delete {row.name}?</strong>{" "}
        <span className="text-muted">{deleteWhy(row.flow_count)}</span>
      </span>
      <div
        data-slot="cat-confirm-actions"
        className="flex flex-wrap justify-end gap-2 phone:flex-nowrap phone:[&>*]:min-h-11 phone:[&>*]:flex-[1_1_auto] phone:[&>*]:px-4 phone:[&>*]:whitespace-nowrap"
      >
        <Button ref={keep} variant="outline" onClick={onKeep}>
          Keep
        </Button>
        <Button variant="danger-solid" onClick={onDelete} disabled={busy}>
          Delete category
        </Button>
      </div>
    </li>
  );
}
