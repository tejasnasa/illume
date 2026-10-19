/**
 * Tests for :component:`RepoCardSkeleton`.
 *
 * The skeleton's job is to render a stable shape during the initial
 * fetch so the dashboard's height does not jump when the real data
 * lands. We pin two things here:
 *
 * - The wrapper exists with the right testID so the dashboard can
 *   assert on it.
 * - The component mounts without throwing -- the Reanimated shared
 *   value initialises in the jest mock, but the surface is small enough
 *   that the smoke check is what matters.
 */

import { render } from "@testing-library/react-native";

import { RepoCardSkeleton } from "@/ui/RepoCardSkeleton";

describe("RepoCardSkeleton", () => {
  it("renders with the default testID", async () => {
    const { getByTestId } = await render(<RepoCardSkeleton />);
    expect(getByTestId("repo-card-skeleton")).toBeTruthy();
  });

  it("honours a custom testID", async () => {
    const { getByTestId } = await render(<RepoCardSkeleton testID="custom" />);
    expect(getByTestId("custom")).toBeTruthy();
  });

  it("exposes an accessibility label for screen readers", async () => {
    const { getByLabelText } = await render(<RepoCardSkeleton />);
    expect(getByLabelText("Loading repository")).toBeTruthy();
  });
});
