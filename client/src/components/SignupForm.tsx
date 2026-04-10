import Link from "next/link";
import Button from "./ui/Button";
import Input from "./ui/Input";

export default function SignupForm() {
  return (
    <form className="bg-transparent w-[55%] p-8 rounded-sm mb-24">
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
        <Input id="name" type="text" placeholder="Tejas Nasa    " />
      </div>

      <div className="flex flex-col my-4 gap-1">
        <label htmlFor="email" className="text-sm">
          Email
        </label>
        <Input id="email" type="email" placeholder="tejas@example.com" />
      </div>

      <div className="flex flex-col my-4 gap-1">
        <label htmlFor="password" className="text-sm">
          Password
        </label>
        <Input id="password" type="password" placeholder="*********" />
      </div>
      <p className="text-(--destructive) my-2 text-sm hidden">
        This is an error message.
      </p>
      <Button className="w-full my-4" size="sm">
        SIGN UP
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
