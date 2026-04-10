"use client";

import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import Textarea from "@/components/ui/Textarea";
import { toast } from "@/lib/use-toast";

export default function Test() {
  return (
    <div className="flex-col flex w-min gap-5 m-5">
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
    </div>
  );
}
