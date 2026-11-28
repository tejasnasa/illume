import { fireEvent, render, screen } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ConversationSwitcher } from "@/components/chat/ConversationSwitcher";
import { routeSummary, planSummary, formatLatency } from "@/components/chat/ActivityBlock";
import { compactCount, formatSeconds, runStatParts } from "@/components/chat/TurnView";
import {
  buildOverrides,
  defaultPreset,
  defaultSettings,
  isCustom,
  loadChoice,
  presetAvailability,
  saveChoice,
} from "@/lib/agent/presets";
import { initialRunState } from "@/lib/agent/reducer";
import { SseParser } from "@/lib/agent/sse";

const mockStore = new Map<string, string>();
jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async (k: string) => mockStore.get(k) ?? null),
    setItem: jest.fn(async (k: string, v: string) => {
      mockStore.set(k, v);
    }),
  },
}));

describe("presets", () => {
  it("gates agent presets and auto on an own key and tool support", () => {
    const free = { hasOwnKey: false, supportsTools: null };
    expect(presetAvailability("deep_agent", free).available).toBe(false);
    expect(presetAvailability("deep_agent_workers", free).available).toBe(false);
    expect(presetAvailability("auto", free).available).toBe(false);
    expect(presetAvailability("classic", free).available).toBe(true);
    const noTools = { hasOwnKey: true, supportsTools: false };
    expect(presetAvailability("deep_agent", noTools).available).toBe(false);
    expect(presetAvailability("hybrid", noTools).available).toBe(true);
    expect(defaultPreset(free)).toBe("classic");
    expect(defaultPreset(noTools)).toBe("hybrid");
    expect(defaultPreset({ hasOwnKey: true, supportsTools: true })).toBe("deep_agent");
  });

  it("sends only the overrides that differ from the preset", () => {
    const base = defaultSettings("deep_agent_workers");
    expect(buildOverrides("deep_agent_workers", base)).toBeUndefined();
    expect(
      buildOverrides("deep_agent_workers", { ...base, maxWorkers: 2 }),
    ).toEqual({ planner: { max_workers: 2 } });
    expect(isCustom("deep_agent", { ...defaultSettings("deep_agent"), rerank: "none" })).toBe(true);
  });

  it("remembers a choice per repository and ignores an unversioned auto", async () => {
    await saveChoice("r1", { preset: "deep_agent_workers", settings: null });
    expect((await loadChoice("r1"))?.preset).toBe("deep_agent_workers");
    mockStore.set("illume.chat.preset.r2", JSON.stringify({ preset: "auto" }));
    expect(await loadChoice("r2")).toBeNull();
    expect(await loadChoice("never")).toBeNull();
  });
});

describe("SseParser", () => {
  it("handles CRLF split across chunks", () => {
    const parser = new SseParser();
    const out = [...parser.push("data: a\r"), ...parser.push("\n\r\ndata: b\n\n")];
    expect(out.map((m) => m.data)).toEqual(["a", "b"]);
  });
});

describe("turn figures", () => {
  it("shortens counts and durations", () => {
    expect(compactCount(950)).toBe("950");
    expect(compactCount(1234)).toBe("1.2k");
    expect(compactCount(25_000)).toBe("25k");
    expect(compactCount(2_500_000)).toBe("2.5M");
    expect(formatSeconds(42)).toBe("42 s");
    expect(formatSeconds(125)).toBe("2 m 5 s");
    expect(formatLatency(null)).toBeNull();
    expect(formatLatency(420)).toBe("420 ms");
    expect(formatLatency(2500)).toBe("2.5 s");
  });

  it("lists nothing for a run that spent nothing", () => {
    expect(runStatParts(initialRunState)).toEqual([]);
  });

  it("describes routing and plans", () => {
    expect(
      routeSummary({
        id: "r",
        laneId: null,
        seq: 1,
        kind: "route",
        route: "deep_question",
        confidence: 0.8,
        resolvedPreset: "deep_agent",
        fallbackReason: null,
      }),
    ).toBe("Routed to Deep agent · deep question · 80%");
    expect(
      routeSummary({
        id: "r",
        laneId: null,
        seq: 1,
        kind: "route",
        route: null,
        confidence: null,
        resolvedPreset: "classic",
        fallbackReason: "timeout",
      }),
    ).toBe("Fell back to Classic (router timed out)");
    expect(
      planSummary({
        id: "p",
        laneId: null,
        seq: 1,
        kind: "plan",
        skipped: false,
        reason: null,
        probability: null,
        subquestions: [{ id: "a", question: "q" }],
      }),
    ).toBe("Split into 1 part, worked on in parallel");
  });
});

describe("ConversationSwitcher", () => {
  const items = [
    {
      id: "c1",
      title: "Auth flow",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      message_count: 2,
    },
  ];

  function renderSwitcher(handlers: Record<string, jest.Mock>) {
    return render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 360, height: 800 },
          insets: { top: 0, left: 0, right: 0, bottom: 0 },
        }}
      >
        <ConversationSwitcher
          open
          items={items}
          activeId={null}
          loaded
          onClose={handlers.onClose}
          onOpen={handlers.onOpen}
          onNew={handlers.onNew}
          onRename={handlers.onRename as never}
          onDelete={handlers.onDelete}
        />
      </SafeAreaProvider>,
    );
  }

  it("opens, starts a new chat and renames inline", async () => {
    const handlers = {
      onClose: jest.fn(),
      onOpen: jest.fn(),
      onNew: jest.fn(),
      onRename: jest.fn(async () => true),
      onDelete: jest.fn(),
    };
    await renderSwitcher(handlers);
    await fireEvent.press(screen.getByText("Auth flow"));
    expect(handlers.onOpen).toHaveBeenCalledWith("c1");
    await fireEvent.press(screen.getByTestId("conversation-new"));
    expect(handlers.onNew).toHaveBeenCalled();
    await fireEvent.press(screen.getByTestId("conversation-rename-c1"));
    await fireEvent.changeText(screen.getByTestId("conversation-rename-input"), "Login");
    await fireEvent.press(screen.getByTestId("conversation-rename-save"));
    expect(handlers.onRename).toHaveBeenCalledWith("c1", "Login");
  });
});
