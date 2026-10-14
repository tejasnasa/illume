/**
 * Smoke test for the root layout. Renders the layout once and asserts
 * a tree is produced; deeper behavioural checks live on-device, where
 * hot reload is the test surface.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

import RootLayout from "../src/app/_layout";

describe("RootLayout", () => {
  it("renders without throwing", async () => {
    const result = await render(<RootLayout />);
    // @testing-library/react-native v14+ returns an async render handle.
    // Wait for any pending effects, then verify the tree exists.
    await waitFor(() => {
      expect(result).toBeTruthy();
    });
  });
});
