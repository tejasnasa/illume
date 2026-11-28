import { fireEvent, render, screen } from "@testing-library/react-native";

import { getGlossary } from "@/api/glossary";
import {
  GLOSSARY_INITIALS,
  GlossaryLetters,
  parseInitial,
} from "@/components/GlossaryLetters";

describe("parseInitial", () => {
  it("accepts a letter in either case and the catch-all", () => {
    expect(parseInitial("g")).toBe("G");
    expect(parseInitial("#")).toBe("#");
    expect(parseInitial("gg")).toBeNull();
    expect(parseInitial("1")).toBeNull();
    expect(parseInitial(undefined)).toBeNull();
    expect(GLOSSARY_INITIALS).toHaveLength(27);
  });
});

describe("GlossaryLetters", () => {
  it("selects an initial with terms and leaves the others inert", async () => {
    const onSelect = jest.fn();
    await render(
      <GlossaryLetters active={null} present={["A", "#"]} onSelect={onSelect} />,
    );
    await fireEvent.press(screen.getByTestId("glossary-letter-A"));
    expect(onSelect).toHaveBeenCalledWith("A");
    await fireEvent.press(screen.getByTestId("glossary-letter-#"));
    expect(onSelect).toHaveBeenLastCalledWith("#");
    await fireEvent.press(screen.getByTestId("glossary-letter-B"));
    expect(onSelect).toHaveBeenCalledTimes(2);
    await fireEvent.press(screen.getByTestId("glossary-letter-all"));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("keeps the active initial pressable even when it has no terms", async () => {
    const onSelect = jest.fn();
    await render(<GlossaryLetters active="Q" present={[]} onSelect={onSelect} />);
    await fireEvent.press(screen.getByTestId("glossary-letter-Q"));
    expect(onSelect).toHaveBeenCalledWith("Q");
  });
});

describe("getGlossary letter", () => {
  it("sends the letter, escaping the catch-all", async () => {
    const fetchImpl = jest.fn(
      async () =>
        new Response(JSON.stringify({ entries: [], total: 0, page: 1, page_size: 20 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    await getGlossary("repo-1", 1, 20, "#", {
      backendUrl: "http://api.test:8000",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url] = fetchImpl.mock.calls[0] as unknown as [string];
    expect(url).toBe(
      "http://api.test:8000/api/v1/repository/repo-1/glossary?page=1&page_size=20&letter=%23",
    );
  });
});
