"use client";

import useRepoForm from "@/hooks/useRepoForm";
import Button from "./ui/Button";
import Input from "./ui/Input";

export default function RepoForm() {
  const { register, onSubmit, isSubmitting } = useRepoForm();
  return (
    <form className="flex flex-col mt-6 gap-2" onSubmit={onSubmit}>
      <label htmlFor="url" className="text-sm text-(--muted-foreground)">
        Repository URL
      </label>
      <Input
        className="w-full"
        id="url"
        placeholder="https://github.com/user/repo"
        {...register("github_url")}
      />

      <Button className="self-end mt-2" size="sm" loading={isSubmitting}>
        Add Repository
      </Button>
    </form>
  );
}
