/**
 * The settings page's account deletion row, confirmed by typing the email.
 * @module DeleteAccount
 */
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Button from "./ui/Button";
import ConfirmBody from "./ui/ConfirmBody";
import Input from "./ui/Input";
import Modal from "./ui/Modal";
import { SettingsRow } from "./ui/SettingsSection";

type Props = {
  /** The account's email, which has to be typed back to confirm. */
  email: string;
  /** What goes with the account, e.g. "6 repositories · 2 tokens". */
  footprint?: string;
};

/**
 * Renders the danger row and its confirmation dialog. The request is made
 * from the browser, not a server action, so the response that clears the
 * session cookie reaches the browser that holds it.
 *
 * @param email - The signed-in account's email.
 * @param footprint - A summary of what the deletion removes, when known.
 * @returns The row.
 */
export default function DeleteAccount({ email, footprint }: Props) {
  const router = useRouter();
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = confirmation.trim().toLowerCase() === email.trim().toLowerCase();

  const handleDelete = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/me`, {
        method: "DELETE",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_email: confirmation }),
      });
      if (!res.ok) throw new Error("Could not delete the account. Try again.");
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the account. Try again.");
      setPending(false);
    }
  };

  return (
    <SettingsRow
      tone="danger"
      title="Delete account"
      description={
        <>
          Deleting your account removes every repository, chat and token. It
          cannot be undone.
          {footprint && (
            <span className="mt-2 block font-pixel text-[11px] tracking-[0.08em] text-(--faint-foreground) uppercase">
              {footprint}
            </span>
          )}
        </>
      }
      action={
        <Modal
          className="w-[min(30rem,calc(100vw-2rem))]"
          dialogLabel="Delete account"
          trigger={
            <Button size="sm" variant="danger" className="shrink-0">
              Delete account
            </Button>
          }
        >
          <ConfirmBody
            title="Delete your account"
            danger
            footer={
              <>
                <span role="alert" className="max-w-[60%] text-xs text-red-300">
                  {error}
                </span>
                <Button
                  onClick={handleDelete}
                  loading={pending}
                  disabled={!matches}
                  size="sm"
                  className="border-none bg-red-500 text-white hover:bg-red-600 disabled:bg-red-500/40"
                >
                  Delete
                </Button>
              </>
            }
          >
            <p className="m-0">
              This permanently deletes your account, every repository and its
              analysis, your chats, and your MCP tokens. Type{" "}
              <span className="font-pixel text-(--foreground)">{email}</span> to confirm.
            </p>
            <Input
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              aria-label="Your email to confirm deletion"
              placeholder={email}
              autoComplete="off"
              className="w-full"
            />
          </ConfirmBody>
        </Modal>
      }
    />
  );
}
