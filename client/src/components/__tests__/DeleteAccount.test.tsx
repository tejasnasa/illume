import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DeleteAccount from "@/components/DeleteAccount";
import { server } from "../../../tests/msw/server";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const ME = `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me`;
const EMAIL = "ada@example.com";

beforeEach(() => {
  router.push.mockReset();
  router.refresh.mockReset();
});

/** Opens the dialog and returns a user-event instance. */
async function open() {
  const user = userEvent.setup();
  render(<DeleteAccount email={EMAIL} footprint="2 repositories" />);
  await user.click(screen.getByRole("button", { name: "Delete account" }));
  return user;
}

describe("DeleteAccount", () => {
  it("shows what goes with the account", () => {
    render(<DeleteAccount email={EMAIL} footprint="2 repositories · 1 token" />);

    expect(screen.getByText("2 repositories · 1 token")).toBeInTheDocument();
  });

  it("keeps Delete disabled until the email is typed back", async () => {
    const user = await open();
    const confirm = screen.getByRole("button", { name: "Delete" });

    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Your email to confirm deletion"), "ADA@example.com");
    expect(confirm).toBeEnabled();
  });

  it("sends the confirmation and leaves for the landing page", async () => {
    let body: unknown = null;
    server.use(
      http.delete(ME, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = await open();

    await user.type(screen.getByLabelText("Your email to confirm deletion"), EMAIL);
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
    expect(body).toEqual({ confirm_email: EMAIL });
  });

  it("says so, and stays put, when the deletion fails", async () => {
    server.use(http.delete(ME, () => HttpResponse.json({}, { status: 500 })));
    const user = await open();

    await user.type(screen.getByLabelText("Your email to confirm deletion"), EMAIL);
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/Could not delete the account/)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });
});
