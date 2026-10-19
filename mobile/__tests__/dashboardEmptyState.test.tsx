/**
 * Tests for :component:`DashboardEmptyState`.
 *
 * The empty state is a single dashed card with a single line of copy.
 * Pinning the copy here catches a silent regression where the web copy
 * -- "No repositories found. Add your first one to get started!" --
 * drifts between web and mobile.
 */

import { render } from "@testing-library/react-native";

import { DashboardEmptyState } from "@/ui/DashboardEmptyState";

describe("DashboardEmptyState", () => {
  it("renders the canonical empty-state copy", async () => {
    const { getByText } = await render(<DashboardEmptyState />);
    expect(
      getByText("No repositories found. Add your first one to get started!"),
    ).toBeTruthy();
  });

  it("exposes a stable testID for the parent screen", async () => {
    const { getByTestId } = await render(<DashboardEmptyState />);
    expect(getByTestId("dashboard-empty")).toBeTruthy();
  });

  it("honours the testID override", async () => {
    const { getByTestId, queryByTestId } = await render(
      <DashboardEmptyState testID="custom-id" />,
    );
    expect(getByTestId("custom-id")).toBeTruthy();
    expect(queryByTestId("dashboard-empty")).toBeNull();
  });
});
