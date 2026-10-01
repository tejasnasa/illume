import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import ContactForm from "@/components/ContactForm";
import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";

const CONTACT_URL = `${BACKEND_URL}/api/v1/contact`;

/**
 * Fills every visible field with a valid submission.
 *
 * Each text field is cleared first: some tests prefill the form from a session, and
 * appending to a prefilled value produces a different (and, for the email, invalid)
 * payload rather than the one the test reads as valid.
 */
async function fillValidForm() {
  const user = userEvent.setup();

  await chooseCategory(user, "Bug report");

  for (const [label, value] of [
    [/^name/i, "Ada Lovelace"],
    [/^email/i, "ada@example.com"],
    [/^message/i, "The graph view does not render on a large repository."],
  ] as const) {
    const field = screen.getByLabelText(label);
    await user.clear(field);
    await user.type(field, value);
  }

  return user;
}

/**
 * Picks a category from the custom listbox.
 *
 * Two clicks rather than `selectOptions`: the control is a button and a list of options,
 * not a `<select>`, so there is no element for the browser to set a value on directly.
 */
async function chooseCategory(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(screen.getByRole("combobox", { name: /what is this about/i }));
  await user.click(screen.getByRole("option", { name: label }));
}

describe("the category control", () => {
  it("is a listbox, not a native select", () => {
    // A native `<select>` cannot be themed: the list it opens is drawn by the operating
    // system, so on this dark-only interface it renders as a light panel that no CSS
    // reaches. The control is therefore a combobox over a drawn listbox.
    render(<ContactForm />);

    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(document.querySelector("select")).toBeNull();
  });

  it("keeps the list closed until it is opened", () => {
    render(<ContactForm />);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("offers every category once opened", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("combobox", { name: /what is this about/i }));

    for (const label of ["Bug report", "Feature request", "Question", "Other"]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
  });

  it("shows the placeholder until a choice is made", () => {
    render(<ContactForm />);

    expect(screen.getByRole("combobox")).toHaveTextContent("Select a category");
  });

  it("shows the chosen label on the trigger and closes the list", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await chooseCategory(user, "Question");

    expect(screen.getByRole("combobox")).toHaveTextContent("Question");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("marks the selected option as selected", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await chooseCategory(user, "Feature request");
    await user.click(screen.getByRole("combobox", { name: /what is this about/i }));

    expect(screen.getByRole("option", { name: "Feature request" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("option", { name: "Other" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("closes on Escape without choosing", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("combobox", { name: /what is this about/i }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveTextContent("Select a category");
  });

  it("chooses with the keyboard, not only the mouse", async () => {
    // The native select gave this for free; leaving it behind means rebuilding it. A
    // dropdown that only responds to a pointer is unusable without one.
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("combobox", { name: /what is this about/i }));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(screen.getByRole("combobox")).toHaveTextContent("Feature request");
  });

  it("closes when a click lands outside it", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("combobox", { name: /what is this about/i }));
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("fields", () => {
  it("prefills the name and email it is given", () => {
    render(<ContactForm defaultName="Grace Hopper" defaultEmail="grace@example.com" />);

    expect(screen.getByLabelText(/name/i)).toHaveValue("Grace Hopper");
    expect(screen.getByLabelText(/email/i)).toHaveValue("grace@example.com");
  });

  it("renders the honeypot but hides it from assistive technology", () => {
    // Present in the DOM -- that is what a bot posts -- and invisible to a person.
    const { container } = render(<ContactForm />);

    const honeypot = container.querySelector("#illume_hp");
    expect(honeypot).toBeInTheDocument();
    expect(honeypot?.closest("[aria-hidden='true']")).not.toBeNull();
    expect(honeypot).toHaveAttribute("tabindex", "-1");
  });

  it("keeps the honeypot out of the tab order and off the screen", () => {
    // `display: none` is skipped by better bots, so the decoy is positioned off-screen.
    const { container } = render(<ContactForm />);

    const wrapper = container.querySelector("#illume_hp")?.closest("div");

    expect(wrapper?.className).toContain("left-[-9999px]");
  });
});

describe("submission", () => {
  it("does not send an incomplete form", async () => {
    let called = false;
    server.use(
      http.post(CONTACT_URL, () => {
        called = true;
        return HttpResponse.json({ message: "ok" });
      }),
    );
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => expect(screen.getByText(/pick a category/i)).toBeInTheDocument());
    expect(called).toBe(false);
  });

  it("shows one banner error rather than one per field", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("button", { name: /send message/i }));

    // Category is first in the error order, so it is the single message shown.
    await waitFor(() => expect(screen.getByText(/pick a category/i)).toBeInTheDocument());
    expect(screen.queryByText(/at least 2 characters/i)).not.toBeInTheDocument();
  });

  it("sends a valid form and reports success", async () => {
    let body: Record<string, string> = {};
    server.use(
      http.post(CONTACT_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ message: "ok" });
      }),
    );
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() =>
      expect(body.message).toBe("The graph view does not render on a large repository."),
    );
    expect(body.category).toBe("bug");
  });

  it("clears the message but keeps the sender's identity afterwards", async () => {
    // A second message should not mean retyping a name and address; leaving the first
    // message in place would invite sending it twice.
    server.use(http.post(CONTACT_URL, () => HttpResponse.json({ message: "ok" })));
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => expect(screen.getByLabelText(/message/i)).toHaveValue(""));
    expect(screen.getByLabelText(/^name/i)).toHaveValue("Ada Lovelace");
    expect(screen.getByLabelText(/^email/i)).toHaveValue("ada@example.com");
    // The category is read off the trigger's label, since the control holds no value
    // attribute of its own.
    expect(screen.getByRole("combobox")).toHaveTextContent("Bug report");
  });

  it("shows the backend's own reason when delivery fails", async () => {
    server.use(
      http.post(CONTACT_URL, () =>
        HttpResponse.json(
          { detail: "Could not deliver your message. Please try again shortly." },
          { status: 502 },
        ),
      ),
    );
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() =>
      expect(screen.getByText(/could not deliver your message/i)).toBeInTheDocument(),
    );
  });

  it("keeps the message in the box when delivery fails", async () => {
    // Losing what the visitor wrote on a delivery failure would make them write it twice.
    server.use(http.post(CONTACT_URL, () => new HttpResponse(null, { status: 502 })));
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() =>
      expect(screen.getByLabelText(/message/i)).toHaveValue(
        "The graph view does not render on a large repository.",
      ),
    );
  });
});
