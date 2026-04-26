import loginimg from "@/assets/loginart6.jpg";
import LoginForm from "@/components/LoginForm";
import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import Link from "next/link";

export default function Login() {
  return (
    <main className="md:flex h-dvh w-dvw overflow-hidden">
      <div className="flex md:hidden flex-col items-center justify-center h-screen gap-4 p-8 text-center">
        <div className="w-16 h-16 rounded-2xl bg-(--card)/60 border border-(--border) backdrop-blur-xl flex items-center justify-center mb-2">
          <span className="text-3xl">🖥️</span>
        </div>
        <h1 className="text-xl font-bold tracking-tight">Desktop Only</h1>
        <p className="text-sm text-(--muted-foreground) leading-relaxed max-w-xs">
          Illume is designed for desktop browsers. Please switch to a larger screen for the best experience.
        </p>
      </div>

      <section className="md:flex w-1/2 hidden flex-col">
        <Link
          href={"/"}
          className="relative h-16 w-16 flex items-center justify-center m-2"
        >
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="h-10 w-10 rounded-full bg-(--chart-1)/30 blur-xl" />
          </div>
          <StarFourIcon
            className="relative text-(--chart-1)"
            weight="fill"
            size={24}
          />
        </Link>
        <div className="flex-1 flex justify-center items-center">
          <LoginForm />
        </div>
      </section>
      <section className="hidden md:block w-1/2 relative overflow-hidden">
        <Image src={loginimg} alt="Login" fill className="object-cover" />
      </section>
    </main>
  );
}
