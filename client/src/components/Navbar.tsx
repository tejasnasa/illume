import logoutAction from "@/actions/logout";
import avatar from "@/assets/loginart.jpg";
import {
  GearSixIcon,
  SignOutIcon,
  StarFourIcon,
  UserIcon,
} from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import Link from "next/link";
import OptionsMenu from "./ui/OptionsMenu";

export default function Navbar() {
  return (
    <header className="flex justify-between">
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

      <OptionsMenu
        trigger={
          <Image
            src={avatar}
            alt="User Avatar"
            className="h-12 w-12 rounded-full m-6 hover:cursor-pointer"
          />
        }
        items={[
          {
            label: "Tejas Nasa",
            icon: <UserIcon size={"inherit"} />,
            disabled: true,
          },
          {
            label: "Settings",
            icon: <GearSixIcon size={"inherit"} />,
          },
          {
            label: "Logout",
            destructive: true,
            icon: <SignOutIcon size={"inherit"} />,
            onClick: logoutAction,
          },
        ]}
        size="lg"
        direction="left"
      />
    </header>
  );
}
