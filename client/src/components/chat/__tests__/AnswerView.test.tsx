import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AnswerView from "@/components/chat/AnswerView";
import { initialRunState, type RunState } from "@/lib/agent/reducer";

const REPO = { url: "https://github.com/acme/app", commitSha: "abc123", branch: "main" };

const CITATIONS = [
  {
    key: "F:app/auth.py:4-8",
    source_type: "symbol",
    file_path: "app/auth.py",
    symbol_name: "hash_password",
    start_line: 4,
    end_line: 8,
    chunk_text: "def hash_password(raw): return bcrypt(raw)",
  },
  {
    key: "F:app/other.py:1-3",
    source_type: "symbol",
    file_path: "app/other.py",
    symbol_name: "other",
    start_line: 1,
    end_line: 3,
    chunk_text: "def other(): pass",
  },
];

function done(answer: string, extra: Partial<RunState> = {}): RunState {
  return {
    ...initialRunState,
    status: "done",
    phase: "finished",
    answer,
    citations: CITATIONS,
    ...extra,
  };
}

describe("AnswerView citations", () => {
  it("renders an inline key as a chip, not as raw bracket text", () => {
    render(
      <AnswerView
        run={done("Passwords are hashed with bcrypt [F:app/auth.py:4-8].")}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    const chip = screen.getByRole("button", { name: "Source F:app/auth.py:4-8" });
    expect(chip).toHaveTextContent("auth.py:4-8");
    expect(screen.getByTestId("answer")).not.toHaveTextContent("[F:app/auth.py");
  });

  it("shows a source preview on hover target and pulses the node", () => {
    const onPulse = vi.fn();
    render(
      <AnswerView
        run={done("See [F:app/auth.py:4-8].")}
        repo={REPO}
        onPulse={onPulse}
      />,
    );
    const chip = screen.getByRole("button", { name: /Source F:app\/auth.py/ });
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.mouseEnter(chip);
    const preview = screen.getByRole("tooltip");
    expect(preview).toHaveTextContent("hash_password");
    expect(preview).toHaveTextContent("app/auth.py:4-8");
    expect(onPulse).toHaveBeenLastCalledWith("app/auth.py");

    fireEvent.mouseLeave(chip);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(onPulse).toHaveBeenLastCalledWith(null);
  });

  it("previews only the hovered chip, not every chip in the answer", () => {
    render(
      <AnswerView
        run={done("See [F:app/auth.py:4-8] and [F:app/auth.py:4-8; C:abc1234].")}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    const chips = screen.getAllByRole("button", { name: /^Source / });
    fireEvent.mouseEnter(chips[0]);
    expect(screen.getAllByRole("tooltip")).toHaveLength(1);
  });

  it("holds back a key that is still being written", () => {
    const run = { ...done("Entry is in [F:app/au"), status: "live" as const };
    render(<AnswerView run={run} repo={REPO} onPulse={() => {}} />);
    expect(screen.getByTestId("answer")).not.toHaveTextContent("[F:app/au");
    expect(screen.getByTestId("answer")).toHaveTextContent("Entry is in");
  });

  it("opens the citation card with a GitHub link at the ingested commit", () => {
    render(
      <AnswerView
        run={done("See [F:app/auth.py:4-8].")}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Source F:app\/auth.py/ }));
    const opened = screen.getByTestId("opened-citation");
    expect(within(opened).getByText("hash_password")).toBeInTheDocument();
    expect(within(opened).getByText(/def hash_password/)).toBeInTheDocument();
    expect(opened.querySelector("a")).toHaveAttribute(
      "href",
      "https://github.com/acme/app/blob/abc123/app/auth.py#L4-L8",
    );
  });

  it("marks a key the run never saw as unresolved and not clickable", () => {
    render(
      <AnswerView
        run={done("Claimed [F:ghost.py:1-2].")}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Source F:ghost.py:1-2" })).toBeDisabled();
  });

  it("keeps keys as quiet text while the answer is still streaming", () => {
    render(
      <AnswerView
        run={done("See [F:app/auth.py:4-8].", { status: "live" })}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /Source/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("answer")).toHaveTextContent("[auth.py:4-8]");
  });

  it("shows cited and also-retrieved sources apart, both folded", () => {
    render(
      <AnswerView
        run={done("Hashing lives in [F:app/auth.py:4-8].")}
        repo={REPO}
        onPulse={() => {}}
      />,
    );
    const cited = screen.getByRole("region", { name: "Sources cited" });
    expect(cited).toHaveTextContent("Sources cited (1)");
    expect(within(cited).queryByText("hash_password")).not.toBeInTheDocument();
    fireEvent.click(within(cited).getByRole("button", { name: /Sources cited/ }));
    expect(within(cited).getByText("hash_password")).toBeInTheDocument();
    expect(within(cited).queryByText("other")).not.toBeInTheDocument();

    const retrieved = screen.getByRole("region", { name: "Also retrieved" });
    expect(retrieved).toHaveTextContent("Also retrieved (1)");
    fireEvent.click(within(retrieved).getByRole("button"));
    expect(within(retrieved).getByText("other")).toBeInTheDocument();
  });
});

describe("AnswerView marks in older answers", () => {
  const answer =
    "Solid claim [F:app/auth.py:4-8]. [[verify:supported]] Shaky claim. [[verify:partially_supported]] " +
    "Wrong claim [F:app/other.py:1-3]. [[verify:contradicted]]";

  it("never shows a raw mark or a badge for one", () => {
    const { container } = render(
      <AnswerView run={done(answer)} repo={REPO} onPulse={() => {}} />,
    );
    expect(screen.getByTestId("answer")).not.toHaveTextContent("verify");
    expect(container.querySelector("[data-verdict]")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
