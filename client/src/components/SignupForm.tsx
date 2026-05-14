"use client";

import useSignupForm from "@/hooks/useSignupForm";
import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import Button from "./ui/Button";
import Input from "./ui/Input";

export default function SignupForm() {
  const { register, firstError, isSubmitting, onSubmit } = useSignupForm();
  return (
    <form
      className="bg-transparent w-[55%] p-8 rounded-sm mb-24"
      onSubmit={onSubmit}
    >
      <h2 className="text-2xl font-bold mb-1 text-center">
        Create your account
      </h2>
      <h4 className="text-(--muted-foreground) text-sm text-center mb-10">
        Get started with Illume for free
      </h4>

      <div className="flex flex-col my-4 gap-1">
        <label htmlFor="name" className="text-sm">
          Name
        </label>
        <Input
          id="name"
          type="text"
          placeholder="Tejas Nasa"
          {...register("name")}
        />
      </div>

      <div className="flex flex-col my-4 gap-1">
        <label htmlFor="email" className="text-sm">
          Email
        </label>
        <Input
          id="email"
          type="email"
          placeholder="tejas@example.com"
          {...register("email")}
        />
      </div>

      <div className="flex flex-col my-4 gap-1">
        <label htmlFor="password" className="text-sm">
          Password
        </label>
        <Input
          id="password"
          type="password"
          placeholder="*********"
          {...register("password")}
        />
      </div>

      {firstError && (
        <p className="text-(--destructive) my-2 text-sm">{firstError}</p>
      )}

      <Button className="w-full mt-1" size="sm" loading={isSubmitting}>
        SIGN UP
      </Button>

      <div className="flex items-center gap-3 w-full my-2">
        <div className="h-px flex-1 bg-linear-to-r from-transparent via-(--border) to-transparent" />
        <span className="text-xs text-(--muted-foreground)/80 tracking-wider font-medium">
          OR
        </span>
        <div className="h-px flex-1 bg-linear-to-r from-transparent via-(--border) to-transparent" />
      </div>

      <Button
        className="bg-white text-black w-full mb-4"
        size="sm"
        onClick={() =>
          (window.location.href = `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/github`)
        }
      >
        <GithubLogoIcon weight="bold" />
        Continue With GitHub
      </Button>

      <div className="text-sm text-center">
        Already have an account?{" "}
        <Link
          href="/login"
          className="text-(--primary) hover:text-(--primary)/90 transition-colors duration-200"
        >
          Log in
        </Link>
      </div>
    </form>
  );
}
