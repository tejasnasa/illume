import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Select from "../Select";

const OPTIONS = [
  { value: "none", label: "None" },
  { value: "cohere", label: "Cohere", disabled: true, reason: "Needs your own API key" },
  { value: "jev", label: "Jev" },
];

function renderSelect(onChange = vi.fn()) {
  render(
    <Select id="rerank" label="Reranker" value="none" onChange={onChange} options={OPTIONS} compact />,
  );
  return onChange;
}

describe("Select", () => {
  it("draws its own list instead of a native select", () => {
    renderSelect();
    expect(document.querySelector("select")).toBeNull();
    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("shows a disabled choice with its reason but does not take it", () => {
    const onChange = renderSelect();
    fireEvent.click(screen.getByRole("combobox"));
    const cohere = screen.getByRole("option", { name: "Cohere" });

    expect(cohere).toHaveAttribute("aria-disabled", "true");
    expect(cohere).toHaveAttribute("title", "Needs your own API key");
    fireEvent.click(cohere);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("skips disabled choices when moving with the arrow keys", () => {
    const onChange = renderSelect();
    const trigger = screen.getByRole("combobox");
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("jev");
  });
});
