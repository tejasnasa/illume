"use client";

import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import OptionsMenu from "@/components/ui/OptionsMenu";
import Skeleton from "@/components/ui/Skeleton";
import Textarea from "@/components/ui/Textarea";
import { toast } from "@/lib/use-toast";

export default function Test() {
  return (
    <div className="flex-col flex gap-5 w-min m-5">
      <Button
        size="md"
        onClick={() =>
          toast({
            title: "Repo analyzed",
            description: "AST graph generated successfully",
            variant: "error",
          })
        }
      >
        Click this
      </Button>
      <Input />
      <Textarea />
      <Modal trigger={<Button>Open Modal</Button>}>
        <div>Hello!</div>
        <Button>click this fr</Button>
      </Modal>
      <Skeleton className="w-64 h-6" />
      <OptionsMenu
        trigger={<Button>Open Options</Button>}
        items={[
          { label: "Option 1" },
          { label: "Option 2" },
          { label: "Option 3" },
        ]}
        size="lg"
        direction="right"
      />
    </div>
  );
}
