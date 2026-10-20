/**
 * Tests for the repository picker route.
 *
 * The route is where the modal-to-detail transition is decided, and the
 * decision matters: the picker is a *route*, so pushing the new
 * repository's page on top of it would leave the picker in the stack and
 * the hardware back button would return to the picker instead of to the
 * dashboard. Replacing swaps the picker out, so back goes to the
 * dashboard -- which is what the user expects after creating a repo.
 */

import React from "react";
import { fireEvent, render, waitFor } from "@testing-library/react-native";
import { router } from "expo-router";

import RepoPickerRoute from "@/app/(app)/repo-picker";

jest.mock("@/components/RepoPickerModal", () => {
  const ReactLocal = require("react");
  const { Text, Pressable } = require("react-native");
  return {
    __esModule: true,
    RepoPickerModal: ({ onClose }: { onClose?: (n: number | null) => void }) =>
      ReactLocal.createElement(
        ReactLocal.Fragment,
        null,
        ReactLocal.createElement(
          Pressable,
          { onPress: () => onClose?.(null) },
          ReactLocal.createElement(Text, null, "dismiss"),
        ),
        ReactLocal.createElement(
          Pressable,
          { onPress: () => onClose?.(42) },
          ReactLocal.createElement(Text, null, "created"),
        ),
      ),
  };
});

jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = {
    push: noop,
    replace: noop,
    back: noop,
    navigate: noop,
    dismiss: noop,
    dismissAll: noop,
    dismissTo: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

/** Every navigation call the route made, in order. */
let calls: { method: string; args: unknown[] }[] = [];

beforeEach(() => {
  calls = [];
  for (const method of ["push", "replace", "back"] as const) {
    (router[method] as unknown as (...args: unknown[]) => void) = (
      ...args: unknown[]
    ) => {
      calls.push({ method, args });
    };
  }
});

describe("RepoPickerRoute", () => {
  it("replaces itself with the new repository's page on success", async () => {
    const screen = await render(<RepoPickerRoute />);

    fireEvent.press(screen.getByText("created"));

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(calls[0].method).toBe("replace");
    expect(calls[0].args[0]).toBe("/(app)/repo/42");
  });

  it("goes back when dismissed without creating anything", async () => {
    const screen = await render(<RepoPickerRoute />);

    fireEvent.press(screen.getByText("dismiss"));

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(calls[0].method).toBe("back");
  });
});
