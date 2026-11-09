import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AdvancedDrawer from "@/components/chat/AdvancedDrawer";
import PresetPicker from "@/components/chat/PresetPicker";
import {
  buildOverrides,
  defaultSettings,
  presetAvailability,
  resolveAuto,
  type Capabilities,
} from "@/lib/agent/presets";

const FREE: Capabilities = { hasOwnKey: false, supportsTools: null };
const KEYED: Capabilities = { hasOwnKey: true, supportsTools: true };
const NO_TOOLS: Capabilities = { hasOwnKey: true, supportsTools: false };

function open(caps: Capabilities, onChoice = vi.fn()) {
  render(
    <PresetPicker
      choice="auto"
      caps={caps}
      custom={false}
      onChoice={onChoice}
      onOpenDrawer={() => {}}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Auto/ }));
  return onChoice;
}

describe("PresetPicker", () => {
  it("lists the five picker presets", () => {
    open(KEYED);
    expect(
      screen.getAllByRole("menuitemradio").map((el) => el.textContent?.split(/(?=[A-Z][a-z])/)[0]),
    ).toHaveLength(5);
    expect(screen.getByRole("menuitemradio", { name: /Deep agent \+ workers/ })).toBeEnabled();
  });

  it("disables agent presets on the free tier and says why", () => {
    open(FREE);
    const deep = screen.getByRole("menuitemradio", { name: /^Deep agent(?!\s*\+)/ });
    expect(deep).toBeDisabled();
    expect(deep).toHaveAttribute("title", expect.stringMatching(/own API key/));
    expect(screen.getByRole("menuitemradio", { name: /^Classic/ })).toBeEnabled();
    expect(screen.getByRole("menuitemradio", { name: /Hybrid/ })).toBeEnabled();
  });

  it("disables agent presets when the model cannot call tools", () => {
    open(NO_TOOLS);
    const workers = screen.getByRole("menuitemradio", { name: /Deep agent \+ workers/ });
    expect(workers).toBeDisabled();
    expect(workers).toHaveAttribute("title", expect.stringMatching(/tool calling/));
    expect(screen.getByRole("menuitemradio", { name: /^Classic/ })).toBeEnabled();
  });

  it("reports the chosen preset", () => {
    const onChoice = open(KEYED);
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Hybrid/ }));
    expect(onChoice).toHaveBeenCalledWith("hybrid");
  });

  it("labels the button 'Custom' when the drawer changed something", () => {
    render(
      <PresetPicker
        choice="deep_agent"
        caps={KEYED}
        custom
        onChoice={() => {}}
        onOpenDrawer={() => {}}
      />,
    );
    expect(screen.getByTestId("preset-label")).toHaveTextContent("Custom");
  });

  it("opens the drawer from the menu", () => {
    const onOpenDrawer = vi.fn();
    render(
      <PresetPicker
        choice="auto"
        caps={KEYED}
        custom={false}
        onChoice={() => {}}
        onOpenDrawer={onOpenDrawer}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Auto/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Advanced settings/ }));
    expect(onOpenDrawer).toHaveBeenCalled();
  });
});

describe("preset logic", () => {
  it("auto resolves by account", () => {
    expect(resolveAuto(FREE)).toBe("classic");
    expect(resolveAuto(NO_TOOLS)).toBe("hybrid");
    expect(resolveAuto(KEYED)).toBe("deep_agent");
  });

  it("agent presets are available only with a tool-capable own key", () => {
    expect(presetAvailability("deep_agent", FREE).available).toBe(false);
    expect(presetAvailability("deep_agent", NO_TOOLS).available).toBe(false);
    expect(presetAvailability("deep_agent", KEYED).available).toBe(true);
    expect(presetAvailability("structural", FREE).available).toBe(true);
  });

  it("sends nothing when the settings equal the preset", () => {
    expect(buildOverrides("deep_agent", defaultSettings("deep_agent"))).toBeUndefined();
  });

  it("sends only the fields that differ", () => {
    const settings = {
      ...defaultSettings("deep_agent"),
      rerank: "none" as const,
      maxIterations: 6,
      channels: ["dense" as const, "lexical" as const],
    };
    expect(buildOverrides("deep_agent", settings)).toEqual({
      channels: ["dense", "lexical"],
      rerank: { kind: "none" },
      agent: { max_iterations: 6 },
    });
  });

  it("does not send agent or planner fields for a single-shot preset", () => {
    const settings = { ...defaultSettings("hybrid"), maxIterations: 3, maxWorkers: 2 };
    expect(buildOverrides("hybrid", settings)).toBeUndefined();
  });
});

describe("AdvancedDrawer", () => {
  function drawer(caps: Capabilities, preset: "deep_agent" | "hybrid" = "deep_agent", onChange = vi.fn()) {
    render(
      <AdvancedDrawer
        open
        preset={preset}
        settings={defaultSettings(preset)}
        caps={caps}
        onClose={() => {}}
        onPreset={() => {}}
        onChange={onChange}
      />,
    );
    return onChange;
  }

  it("shows the preset name, and 'custom' after a change", () => {
    const { rerender } = render(
      <AdvancedDrawer
        open
        preset="deep_agent"
        settings={defaultSettings("deep_agent")}
        caps={KEYED}
        onClose={() => {}}
        onPreset={() => {}}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("drawer-preset-name")).toHaveTextContent("Preset: Deep agent");
    rerender(
      <AdvancedDrawer
        open
        preset="deep_agent"
        settings={{ ...defaultSettings("deep_agent"), maxIterations: 5 }}
        caps={KEYED}
        onClose={() => {}}
        onPreset={() => {}}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("drawer-preset-name")).toHaveTextContent("Preset: custom");
  });

  it("on the free tier, does not let a channel be added", () => {
    drawer(FREE, "hybrid");
    expect(screen.getByRole("checkbox", { name: "grep" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "dense" })).toBeEnabled();
  });
});
