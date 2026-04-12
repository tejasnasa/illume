import { useRouter } from "next/navigation";
import { useState } from "react";

export default function useLogout() {
  const router = useRouter();
  const [loading, setLoading] = useState<boolean>(false);

  const logout = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/auth/logout`,
        {
          method: "POST",
          credentials: "include",
        },
      );

      if (!res.ok) {
        throw new Error("Failed to logout");
      }

      router.push("/login");
    } catch (error) {
      alert((error as { message?: string }).message ?? "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return { logout, loading };
}
