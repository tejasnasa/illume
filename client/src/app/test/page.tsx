import Button from "@/ui/Button";
import Input from "@/ui/Input";
import Textarea from "@/ui/Textarea";

export default function Test() {
  return (
    <div className="flex-col flex w-min gap-5 m-5">
      <Button loading size="md">
        Click this
      </Button>
      <Input />
      <Textarea />
    </div>
  );
}
