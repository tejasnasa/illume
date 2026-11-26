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
 * Picks a category card. Each card is a label around a visually hidden radio,
 * so clicking the radio by its accessible name is what a pointer on the card does.
 */
async function chooseCategory(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  await user.click(screen.getByRole("radio", { name: new RegExp(`^${title}`) }));
}

describe("the category control", () => {
  it("is a group of radio cards under one legend", () => {
    render(<ContactForm />);

    const group = screen.getByRole("group", { name: /what is this about/i });
    expect(group.tagName).toBe("FIELDSET");
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(document.querySelector("select")).toBeNull();
  });

  it("offers every category, each with a line on what it is for", () => {
    render(<ContactForm />);

    for (const [title, blurb] of [
      ["Bug report", "Something broke or looks wrong"],
      ["Feature idea", "Something Illume should do"],
      ["Question", "How something works"],
      ["Something else", "Feedback, hello, anything"],
    ]) {
      expect(screen.getByRole("radio", { name: new RegExp(`^${title}`) })).toBeInTheDocument();
      expect(screen.getByText(blurb)).toBeInTheDocument();
    }
  });

  it("starts with nothing chosen", () => {
    render(<ContactForm />);

    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
  });

  it("checks the chosen card and only that one", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await chooseCategory(user, "Feature idea");

    expect(screen.getByRole("radio", { name: /^Feature idea/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Question/ })).not.toBeChecked();
  });

  it("chooses with the keyboard, not only the mouse", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await chooseCategory(user, "Bug report");
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("radio", { name: /^Feature idea/ })).toBeChecked();
  });

  it("fits the message hint to the chosen category", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await chooseCategory(user, "Feature idea");

    expect(screen.getByLabelText(/^message/i)).toHaveAttribute(
      "placeholder",
      expect.stringMatching(/the problem it would solve/i),
    );
  });
});

describe("fields", () => {
  it("prefills the name and email it is given", () => {
    render(
      <ContactForm
        defaultName="Grace Hopper"
        defaultEmail="grace@example.com"
      />,
    );

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

    await waitFor(() =>
      expect(screen.getByText(/pick a category/i)).toBeInTheDocument(),
    );
    expect(called).toBe(false);
  });

  it("shows one banner error rather than one per field", async () => {
    const user = userEvent.setup();
    render(<ContactForm />);

    await user.click(screen.getByRole("button", { name: /send message/i }));

    // Category is first in the error order, so it is the single message shown.
    await waitFor(() =>
      expect(screen.getByText(/pick a category/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/at least 2 characters/i),
    ).not.toBeInTheDocument();
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
      expect(body.message).toBe(
        "The graph view does not render on a large repository.",
      ),
    );
    expect(body.category).toBe("bug");
    const sent = await screen.findByRole("status");
    expect(sent).toHaveTextContent(/message sent/i);
    // The form has gone, so focus moves to the heading that replaced it.
    expect(screen.getByRole("heading", { name: /on its way/i })).toHaveFocus();
  });

  it("clears the message but keeps the sender's identity afterwards", async () => {
    // A second message should not mean retyping a name and address; leaving the first
    // message in place would invite sending it twice.
    server.use(
      http.post(CONTACT_URL, () => HttpResponse.json({ message: "ok" })),
    );
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));
    await user.click(await screen.findByRole("button", { name: /send another/i }));

    expect(screen.getByLabelText(/^message/i)).toHaveValue("");
    expect(screen.getByLabelText(/^name/i)).toHaveValue("Ada Lovelace");
    expect(screen.getByLabelText(/^email/i)).toHaveValue("ada@example.com");
    expect(screen.getByRole("radio", { name: /^Bug report/ })).toBeChecked();
  });

  it("shows the backend's own reason when delivery fails", async () => {
    server.use(
      http.post(CONTACT_URL, () =>
        HttpResponse.json(
          {
            detail: "Could not deliver your message. Please try again shortly.",
          },
          { status: 502 },
        ),
      ),
    );
    render(<ContactForm />);

    const user = await fillValidForm();
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/could not deliver your message/i),
      ).toBeInTheDocument(),
    );
  });

  it("keeps the message in the box when delivery fails", async () => {
    // Losing what the visitor wrote on a delivery failure would make them write it twice.
    server.use(
      http.post(CONTACT_URL, () => new HttpResponse(null, { status: 502 })),
    );
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
