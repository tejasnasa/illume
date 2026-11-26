/**
 * GitHub sign-in panel: the login page's left half.
 * @module LoginForm
 */
"use client";

import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import { useState } from "react";

/**
 * Renders the headline and the single GitHub action.
 *
 * GitHub is the only way in: continuing creates the account on first use, so
 * there is no separate sign-up form. The button hands the browser to the
 * backend's OAuth start, and shows a busy state until the redirect lands.
 *
 * @returns The sign-in panel.
 */
export default function LoginForm() {
  const [loading, setLoading] = useState(false);

  return (
    <div className="flex w-full max-w-105 flex-col gap-7">
      <div className="flex flex-col gap-3.5">
        <p className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)">
          &gt; illume login<span className="caret text-(--accent)">_</span>
        </p>
        <h1 className="m-0 font-pixel text-[clamp(2.2rem,3.6vw,3.2rem)] leading-[1.04] tracking-[-0.02em]">
          Welcome back,
          <br />
          <span className="gradient-text">your map is waiting</span>
        </h1>
        <p className="m-0 text-base leading-relaxed text-zinc-400">
          Continue with GitHub to pick up where you left off: your
          repositories, guides and chats, kept current with main.
        </p>
      </div>

      <button
        type="button"
        disabled={loading}
        aria-busy={loading}
        onClick={() => {
          setLoading(true);
          window.location.href = `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/github`;
        }}
        className="cta flex items-center justify-center gap-3 rounded-sm bg-(--primary) px-5 py-4 font-pixel text-base tracking-[0.04em] text-(--primary-foreground) hover:cursor-pointer disabled:cursor-wait disabled:opacity-80"
      >
        <GithubLogoIcon weight="fill" size={20} aria-hidden="true" />
        {loading ? "Opening GitHub…" : "Continue with GitHub"}
      </button>

      <p className="m-0 text-sm leading-relaxed text-(--subtle-foreground)">
        New here? Continuing with GitHub creates your account.
      </p>
    </div>
  );
}
