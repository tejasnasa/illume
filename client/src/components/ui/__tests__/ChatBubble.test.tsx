import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ChatBubble from "@/components/ui/ChatBubble";
import type ChatMessage from "@/types/chat";

const URL = "https://github.com/example/cool-project";

/** The shape `ChatMessage.sources` declares, for the builder below. */
type Source = ChatMessage["sources"][number];

/**
 * A citation as `POST /chat` returns one, with the fields that do not apply to a symbol
 * set to `null` rather than omitted. The client's type declares all ten as non-nullable,
 * so the cast is needed to build a faithful fixture.
 */
function source(fields: Partial<Source> & { source_type: string; chunk_text: string }): Source {
  return {
    file_path: null,
    symbol_name: null,
    start_line: null,
    end_line: null,
    commit_hash: null,
    author_name: null,
    pr_number: null,
    pr_title: null,
    ...fields,
  } as unknown as Source;
}

const ANSWER = {
  answer: "It lowercases the input.",
  sources: [
    source({
      source_type: "symbol",
      chunk_text: "def slugify(text): ...",
      file_path: "src/util.py",
      symbol_name: "slugify",
      start_line: 4,
      end_line: 6,
    }),
  ],
};

/** Renders a bubble with sensible defaults, overridable per test. */
function renderBubble(props: Partial<React.ComponentProps<typeof ChatBubble>> = {}) {
  return render(
    <ChatBubble
      id="m1"
      question="What does slugify do?"
      message={ANSWER}
      url={URL}
      {...props}
    />,
  );
}

describe("question", () => {
  it("renders the question text", () => {
    renderBubble();

    expect(screen.getByText("What does slugify do?")).toBeInTheDocument();
  });

  it("renders the question while the answer is still pending", () => {
    // The optimistic bubble is what makes the UI feel immediate; the question must not
    // wait for the answer to appear.
    renderBubble({ message: null });

    expect(screen.getByText("What does slugify do?")).toBeInTheDocument();
  });

  it("renders the question even when the turn failed", () => {
    renderBubble({ error: true, message: { answer: "Failed to get response.", sources: [] } });

    expect(screen.getByText("What does slugify do?")).toBeInTheDocument();
  });
});

describe("pending state", () => {
  it("shows a progress message instead of the answer", () => {
    renderBubble({ message: null });

    expect(screen.getByText("Analyzing codebase...")).toBeInTheDocument();
  });

  it("renders no delete button while pending", () => {
    // A pending turn has no persisted id yet, so there is nothing to delete server-side.
    renderBubble({ message: null, onDelete: vi.fn() });

    expect(screen.queryByTitle("Delete message")).not.toBeInTheDocument();
  });

  it("does not render citation cards while pending", () => {
    renderBubble({ message: null });

    expect(screen.queryByText(/Sources Cited/)).not.toBeInTheDocument();
  });
});

describe("answer", () => {
  it("renders the answer text", () => {
    renderBubble();

    expect(screen.getByText("It lowercases the input.")).toBeInTheDocument();
  });

  it("renders markdown rather than the raw source", () => {
    // The backend prompt asks for prose with file and symbol names in it; models
    // routinely return markdown, and the chat reads as broken if it is shown literally.
    renderBubble({ message: { answer: "Use `slugify()` here.", sources: [] } });

    expect(screen.getByText("slugify()")).toBeInTheDocument();
    expect(screen.queryByText(/`slugify\(\)`/)).not.toBeInTheDocument();
  });

  it("renders no source section when there are none", () => {
    renderBubble({ message: { answer: "An answer with no citations.", sources: [] } });

    expect(screen.queryByText(/Sources Cited/)).not.toBeInTheDocument();
  });

  it("renders no source section when sources are null", () => {
    // The JSONB column is nullable, and old rows have no sources at all.
    renderBubble({ message: { answer: "An answer.", sources: null as never } });

    expect(screen.queryByText(/Sources Cited/)).not.toBeInTheDocument();
  });
});

describe("citations", () => {
  it("counts the sources", () => {
    renderBubble();

    expect(screen.getByText("Sources Cited (1)")).toBeInTheDocument();
  });

  it("counts more than one", () => {
    renderBubble({
      message: {
        answer: "An answer.",
        sources: [ANSWER.sources[0], { ...ANSWER.sources[0], symbol_name: "other" }],
      },
    });

    expect(screen.getByText("Sources Cited (2)")).toBeInTheDocument();
  });

  it("renders a card per source", () => {
    renderBubble();

    expect(screen.getByText("slugify")).toBeInTheDocument();
  });
});

describe("failure state", () => {
  it("renders the retry message as the answer", () => {
    renderBubble({
      error: true,
      message: { answer: "Failed to get response. Try again.", sources: [] },
    });

    expect(screen.getByText("Failed to get response. Try again.")).toBeInTheDocument();
  });

  it("still offers deletion for a failed turn", () => {
    // Deleting a failed turn only removes the local bubble -- the hook skips the server
    // call for it -- but the affordance is present, and a user clearing a mistake
    // expects it to be.
    renderBubble({
      error: true,
      message: { answer: "Failed to get response. Try again.", sources: [] },
      onDelete: vi.fn(),
    });

    expect(screen.getByTitle("Delete message")).toBeInTheDocument();
  });
});

describe("deletion", () => {
  it("renders no delete button without a handler", () => {
    renderBubble({ onDelete: undefined });

    expect(screen.queryByTitle("Delete message")).not.toBeInTheDocument();
  });

  it("calls the handler with this bubble's id", () => {
    // The id is what the delete endpoint addresses, so passing the wrong one would
    // remove a different turn -- the message id, not the array index.
    const onDelete = vi.fn();
    renderBubble({ id: "the-message-id", onDelete });

    return userEvent
      .setup()
      .click(screen.getByTitle("Delete message"))
      .then(() => expect(onDelete).toHaveBeenCalledWith("the-message-id"));
  });

  it("does not call the handler on render", () => {
    const onDelete = vi.fn();
    renderBubble({ onDelete });

    expect(onDelete).not.toHaveBeenCalled();
  });
});
