import { screen, waitFor } from "@testing-library/react";
import { Outlet, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import { renderRoute } from "@/test/utils";

import { Button } from "./button";
import {
  RouteSheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetError,
  SheetFooter,
  SheetHeader,
} from "./sheet";

function Page() {
  const { pathname } = useLocation();
  return (
    <>
      <p>Page at {pathname}</p>
      <Outlet />
    </>
  );
}

function Drawer() {
  return (
    <RouteSheet closeTo="/accounts">
      <SheetContent kind="asset">
        <SheetHeader eyebrow="Assets" title="New account" />
        <SheetBody>
          <SheetError>Name is required</SheetError>
          <input aria-label="Name" data-autofocus="" />
        </SheetBody>
        <SheetFooter>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </RouteSheet>
  );
}

const routes = [
  {
    element: <Page />,
    children: [
      { path: "accounts", element: null },
      { path: "accounts/new", element: <Drawer /> },
    ],
  },
];

describe("RouteSheet", () => {
  it("is a titled dialog over the page", () => {
    renderRoute("/accounts/new", { routes });
    const dialog = screen.getByRole("dialog", { name: "New account" });
    expect(dialog).toHaveTextContent("Assets");
    expect(screen.getByRole("alert")).toHaveTextContent("Name is required");
    // The page is still rendered behind it.
    expect(screen.getByText("Page at /accounts/new")).toBeInTheDocument();
  });

  it("focuses the field marked data-autofocus, not the ✕", async () => {
    renderRoute("/accounts/new", { routes });
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus(),
    );
  });

  it.each([
    ["the ✕", "Close"],
    ["Cancel", "Cancel"],
  ])("closes to its page with %s", async (_, name) => {
    const { user, router } = renderRoute("/accounts/new", { routes });
    await user.click(screen.getByRole("button", { name }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/accounts"),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const { user, router } = renderRoute("/accounts/new", { routes });
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/accounts"),
    );
  });
});
