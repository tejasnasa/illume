"use client";

import useRepoForm from "@/hooks/useRepoForm";
import Button from "./ui/Button";
import Input from "./ui/Input";

export default function RepoForm() {
  const { register, onSubmit, isSubmitting, firstError } = useRepoForm();
  return (
    <form className="flex flex-col mt-6 gap-2 w-full" onSubmit={onSubmit}>
      <Input
        className="w-full"
        id="url"
        placeholder="https://github.com/user/repo"
        {...register("github_url")}
      />

      {firstError && <p className="text-(--destructive) text-xs">{firstError}</p>}

      <Button className="w-full mt-2" size="sm" loading={isSubmitting}>
        Add Repository
      </Button>
    </form>
  );
}
