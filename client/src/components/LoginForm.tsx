/**
 * GitHub OAuth entry screen for existing users.
 * @module LoginForm
 */
"use client";

import {
  EyeIcon,
  LockIcon,
  ProhibitIcon,
  StarFourIcon,
} from "@phosphor-icons/react";
import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { useState } from "react";
import Button from "./ui/Button";

/**
 * Renders the centered login card with a GitHub continue action.
 *
 * @returns Login screen that redirects to backend GitHub OAuth.
 */
export default function LoginForm() {
  const [loading, setLoading] = useState(false);

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-(--background)">
      <div className="relative w-full max-w-md overflow-hidden rounded-sm border p-16 flex flex-col items-center gap-4 mb-20">
        <div className="pointer-events-none rounded-full bg-(--chart-1)/10 blur-3xl" />

        <Link
          href="/"
          className="relative flex h-16 w-16 items-center justify-center"
        >
          <div className="absolute inset-0 rounded-full bg-(--chart-1)/20 blur-lg" />
          <div className="relative flex h-12 w-12 items-center justify-center rounded-full  ">
            <StarFourIcon
              weight="fill"
              size={32}
              className="text-(--chart-1)"
            />
          </div>
        </Link>

        <div className="flex flex-col items-center gap-1 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-(--foreground)">
            Welcome to Illume
          </h1>
          <p className="text-sm text-(--muted-foreground)">
            Login to analyze your codebase
          </p>
        </div>

        <div className="w-full h-px bg-(--border)" />

        <div className="w-full flex flex-col gap-3">
          <Button
            loading={loading}
            size="sm"
            className="w-full bg-white text-black hover:bg-(--foreground)/90 disabled:bg-white/70 font-semibold mb-4"
            onClick={() => {
              setLoading(true);
              window.location.href = `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/github`;
            }}
          >
            <GithubLogoIcon weight="bold" size={16} />
            Continue with GitHub
          </Button>

          <div className="grid grid-cols-3 gap-2">
            {[
              { icon: <EyeIcon />, label: "Read-only" },
              { icon: <ProhibitIcon />, label: "Never stored" },
              { icon: <LockIcon />, label: "Private repos" },
            ].map(({ icon, label }) => (
              <div
                key={label}
                className="flex flex-col items-center gap-1 rounded-lg border py-2 px-1"
              >
                <span className="text-2xl m-1 text-(--primary)">{icon}</span>
                <span className="text-[11px] text-(--muted-foreground) text-center leading-tight">
                  {label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
