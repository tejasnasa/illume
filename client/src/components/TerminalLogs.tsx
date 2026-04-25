"use client";

import {
  CircleDashedIcon,
  TerminalWindowIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export default function TerminalLogs({
  repoId,
  token,
}: {
  repoId: string;
  token: string;
}) {
  const router = useRouter();
  const [logs, setLogs] = useState<any[]>([
    { text: "Connecting to ingestion pipeline...", type: "system", time: "" },
  ]);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    const wsUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL!.replace(/^http/, "ws") +
      `/api/v1/ws/ingest/${repoId}?token=${token}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setLogs((prev) => [
        ...prev,
        { text: "Connected. Waiting for worker...", type: "system", time: "" },
      ]);
    };

    ws.onmessage = (event) => {
      let data = event.data;
      let logMessage = data;
      let eventType = "info";

      try {
        const parsed = JSON.parse(data);
        logMessage = parsed.message || data;
        eventType = parsed.event || "info";

        if (eventType === "status_update") {
          router.refresh();
        }
      } catch (e) {}

      if (data === "DONE") {
        setLogs((prev) => [
          ...prev,
          {
            text: "Ingestion finished successfully. Reloading data...",
            type: "success",
            time: "",
          },
        ]);
        setTimeout(() => {
          router.refresh();
        }, 1000);
      } else if (data === "ERROR") {
        setLogs((prev) => [
          ...prev,
          { text: "Ingestion failed!", type: "error", time: "" },
        ]);
        setTimeout(() => {
          router.refresh();
        }, 2000);
      } else {
        setLogs((prev) => [
          ...prev,
          {
            text: logMessage,
            type: eventType,
            time: new Date().toLocaleTimeString([], {
              hour12: false,
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }),
          },
        ]);
      }
    };

    ws.onerror = () => {
      setLogs((prev) => [
        ...prev,
        { text: "WebSocket connection error.", type: "error", time: "" },
      ]);
    };

    ws.onclose = () => {
      setLogs((prev) => [
        ...prev,
        { text: "Connection closed.", type: "system", time: "" },
      ]);
    };

    return () => {
      ws.close();
    };
  }, [repoId, token, router]);

  const getLogColor = (type: string) => {
    if (type === "error" || type.includes("failed")) return "text-red-400";
    if (type === "success" || type === "done") return "text-green-400";
    if (type.includes("started")) return "text-blue-400";
    if (type.includes("complete")) return "text-emerald-400";
    if (type === "status_update") return "text-yellow-400 font-bold";
    return "text-[#c9d1d9]";
  };

  return (
    <div className="w-full h-full flex flex-col text-(--muted-foreground) font-mono text-sm relative">
      <div className="flex items-center gap-2 p-4 border-b border-(--border) bg-(--background)/40 shrink-0">
        <TerminalWindowIcon size={24} className="text-(--primary)" />
        <span className="font-semibold tracking-wide uppercase text-sm">
          Ingestion Terminal
        </span>
        <CircleDashedIcon
          size={14}
          className="animate-spin text-yellow-500 ml-auto"
        />
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-1 custom-scrollbar pb-1">
        {logs.map((log, i) => (
          <div key={i} className="flex gap-3 leading-relaxed">
            {log.time && (
              <span className="text-(--foreground)/20 shrink-0 select-none">
                [{log.time}]
              </span>
            )}
            <span className="text-(--foreground)/30 shrink-0 select-none">{">"}</span>
            <span className={getLogColor(log.type)}>{log.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

    </div>
  );
}
