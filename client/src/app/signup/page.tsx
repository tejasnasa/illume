import loginimg from "@/assets/loginart6.jpg";
import SignupForm from "@/components/SignupForm";
import { StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import Link from "next/link";

export default function Signup() {
  return (
    <main className="flex h-dvh w-dvw overflow-hidden">
      <section className="w-1/2 relative overflow-hidden">
        <Image src={loginimg} alt="Login" fill className="object-cover" />
      </section>
      <section className="w-1/2 flex flex-col">
        <Link
          href={"/"}
          className="relative h-16 w-16 flex items-center justify-center m-2 self-end"
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
          <SignupForm />
        </div>
      </section>
    </main>
  );
}
