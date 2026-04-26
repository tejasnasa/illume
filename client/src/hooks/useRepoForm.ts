import { repoCreateSchema } from "@/types/validators";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

export default function useRepoForm() {
  const router = useRouter();
  const form = useForm<z.infer<typeof repoCreateSchema>>({
    resolver: zodResolver(repoCreateSchema),
    defaultValues: { github_url: "" },
  });

  const { github_url, root } = form.formState.errors;
  const firstError = github_url?.message || root?.message;

  const onSubmit = form.handleSubmit(async (data) => {
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(data),
        },
      );

      if (!res.ok) {
        const error = await res.json();
        throw new Error(
          error.message ?? "Something went wrong. Please try again.",
        );
      }
      const result = await res.json();
      router.push(`/repo/${result.repo_num}`);
    } catch (error) {
      alert((error as Error).message);
    }
  });

  return {
    firstError,
    register: form.register,
    isSubmitting: form.formState.isSubmitting,
    onSubmit,
  };
}
