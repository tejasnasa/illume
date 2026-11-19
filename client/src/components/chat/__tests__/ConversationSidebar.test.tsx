import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ConversationSidebar, {
  type ConversationSidebarProps,
} from "@/components/chat/ConversationSidebar";
import type { ConversationSummary } from "@/types/conversation";

const ITEMS: ConversationSummary[] = [
  {
    id: "c1",
    title: "How does auth work",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
    message_count: 2,
  },
  {
    id: "c2",
    title: "Where is the router",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: new Date(Date.now() - 3 * 86400 * 1000).toISOString(),
    message_count: 1,
  },
];

function setup(props: Partial<ConversationSidebarProps> = {}) {
  const handlers = {
    onClose: vi.fn(),
    onSelect: vi.fn(),
    onNew: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
  };
  render(
    <ConversationSidebar
      items={ITEMS}
      loaded
      activeId="c1"
      drawer={false}
      open
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("ConversationSidebar list", () => {
  it("shows each title with its relative time and highlights the active one", () => {
    setup();

    const active = screen.getByRole("button", { name: /^How does auth work/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(active).toHaveTextContent("3 hours ago");
    const other = screen.getByRole("button", { name: /^Where is the router/ });
    expect(other).not.toHaveAttribute("aria-current");
    expect(other).toHaveTextContent("3 days ago");
  });

  it("says so when there are none, and while loading", () => {
    const { rerender } = render(
      <ConversationSidebar
        items={[]}
        loaded={false}
        activeId={null}
        drawer={false}
        open
        onClose={vi.fn()}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("conversation-rows-skeleton"),
    ).toBeInTheDocument();

    rerender(
      <ConversationSidebar
        items={[]}
        loaded
        activeId={null}
        drawer={false}
        open
        onClose={vi.fn()}
        onSelect={vi.fn()}
        onNew={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
  });

  it("selects a conversation and starts a new chat", async () => {
    const handlers = setup();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: /^Where is the router/ }),
    );
    await user.click(screen.getByRole("button", { name: "New chat" }));

    expect(handlers.onSelect).toHaveBeenCalledWith("c2");
    expect(handlers.onNew).toHaveBeenCalledTimes(1);
  });
});

describe("ConversationSidebar rename", () => {
  it("renames on Enter with the trimmed title", async () => {
    const handlers = setup();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Options for How does auth work" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const field = screen.getByRole("textbox", { name: "Conversation title" });
    expect(field).toHaveValue("How does auth work");
    expect(field).toHaveAttribute("maxlength", "120");
    await user.clear(field);
    await user.type(field, "  Auth flow  {Enter}");

    expect(handlers.onRename).toHaveBeenCalledWith("c1", "Auth flow");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("cancels on Escape and ignores a blank or unchanged title", async () => {
    const handlers = setup();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Options for How does auth work" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    await user.type(screen.getByRole("textbox"), "zzz{Escape}");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Options for How does auth work" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "   {Enter}");

    await user.click(
      screen.getByRole("button", { name: "Options for How does auth work" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    await user.type(screen.getByRole("textbox"), "{Enter}");

    expect(handlers.onRename).not.toHaveBeenCalled();
  });
});

describe("ConversationSidebar delete", () => {
  it("asks first, and deletes only when confirmed", async () => {
    const handlers = setup();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Options for Where is the router" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog");
    expect(handlers.onDelete).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(handlers.onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Options for Where is the router" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    expect(handlers.onDelete).toHaveBeenCalledWith("c2");
  });
});

describe("ConversationSidebar drawer", () => {
  it("renders nothing while closed", () => {
    setup({ drawer: true, open: false });

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("closes after a choice or a new chat, and from its close buttons", async () => {
    const handlers = setup({ drawer: true, open: true });
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: /^Where is the router/ }),
    );
    expect(handlers.onSelect).toHaveBeenCalledWith("c2");
    expect(handlers.onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(handlers.onNew).toHaveBeenCalledTimes(1);
    expect(handlers.onClose).toHaveBeenCalledTimes(2);

    await user.click(
      screen.getAllByRole("button", { name: "Close conversations" })[0],
    );
    expect(handlers.onClose).toHaveBeenCalledTimes(3);
  });
});
