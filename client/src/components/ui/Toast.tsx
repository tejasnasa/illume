"use client";

import { useToastStore } from "@/lib/use-toast";
import {
  CheckCircleIcon,
  InfoIcon,
  XCircleIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useEffect } from "react";

export function Toast() {
  const { state, subscribe } = useToastStore();

  useEffect(() => {
    return subscribe();
  }, [subscribe]);

  return (
    <div className="fixed top-6 right-6 z-100 flex flex-col gap-3">
      {state.map((toast) => (
        <ToastItem key={toast.id} {...toast} />
      ))}
    </div>
  );
}

function ToastItem({
  title,
  description,
  variant = "default",
}: {
  title?: string;
  description?: string;
  variant?: "default" | "success" | "error";
}) {
  const variantStyles = {
    default: "border-(--foreground) text-(--foreground)",
    success: "border-(--chart-1) text-(--chart-1)",
    error: "border-(--destructive) text-(--destructive)",
  };

  const iconMap = {
    default: <InfoIcon size={40} className="text-(--muted-foreground)" />,
    success: <CheckCircleIcon size={40} className="text-(--chart-1)" />,
    error: <XCircleIcon size={40} className="text-(--destructive)" />,
  };

  return (
    <div
      className={`w-[320px] rounded-xl border px-4 py-3 shadow-lg backdrop-blur-xl animate-in fade-in slide-in-from-right flex gap-3 items-center justify-center ${variantStyles[variant]}`}
    >
      <div className="flex items-center justify-center rounded-md ">
        {iconMap[variant]}
      </div>
      <div className="flex-1">
        {title && <div className="text-md font-semibold mb-1">{title}</div>}
        {description && (
          <div className="text-xs text-(--muted-foreground)">{description}</div>
        )}
      </div>
    </div>
  );
}
