import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Switch from "@/components/ui/Switch";

/**
 * Pins the accessibility contract of the Switch: a native checkbox wired up
 * with the WAI-ARIA switch pattern. Anything that touches the rendered markup
 * is likely to break screen-reader behaviour, so the assertions here are
 * deliberately strict on role and aria-checked.
 */
describe("the accessibility contract", () => {
  it("renders as a switch", () => {
    render(<Switch checked={false} onChange={() => {}} aria-label="Enable" />);
    expect(screen.getByRole("switch", { name: "Enable" })).toBeInTheDocument();
  });

  it("reports aria-checked=true when checked", () => {
    render(<Switch checked={true} onChange={() => {}} aria-label="Enable" />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("reports aria-checked=false when unchecked", () => {
    render(<Switch checked={false} onChange={() => {}} aria-label="Enable" />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });
});

describe("user interaction", () => {
  it("fires onChange when clicked", async () => {
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} aria-label="Enable" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("switch"));

    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("forwards the native disabled attribute", () => {
    render(
      <Switch
        checked={false}
        disabled
        onChange={() => {}}
        aria-label="Enable"
      />,
    );
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});

describe("the label prop", () => {
  it("renders an inline label when supplied", () => {
    render(<Switch checked={false} onChange={() => {}} label="Auto-update" />);
    expect(screen.getByText("Auto-update")).toBeInTheDocument();
  });

  it("renders nothing when no label is supplied", () => {
    render(<Switch checked={false} onChange={() => {}} aria-label="Enable" />);
    expect(screen.queryByText("Auto-update")).not.toBeInTheDocument();
  });
});
