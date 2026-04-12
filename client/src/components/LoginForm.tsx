"use client";

import useLoginForm from "@/hooks/useLoginForm";
import Link from "next/link";
import Button from "./ui/Button";
import Input from "./ui/Input";

export default function LoginForm() {
  const { register, firstError, isSubmitting, onSubmit } = useLoginForm();
  return (
    <form
      className="bg-transparent w-[55%] p-8 rounded-sm mb-24"
      onSubmit={onSubmit}
    >
      <h2 className="text-2xl font-bold mb-1 text-center">
        Login to your account
      </h2>
      <h4 className="text-(--muted-foreground) text-sm text-center mb-10">
        Enter your email below to login to your account
      </h4>

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
        <p className="text-(--destructive) my-2 text-sm hidden">{firstError}</p>
      )}

      <Button className="w-full my-4" size="sm" loading={isSubmitting}>
        LOGIN
      </Button>

      <div className="text-sm text-center">
        Don't have an account?{" "}
        <Link
          href="/signup"
          className="text-(--primary) hover:text-(--primary)/90 transition-colors duration-200"
        >
          Sign up
        </Link>
      </div>
    </form>
  );
}
