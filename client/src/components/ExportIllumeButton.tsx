"use client";

import { useState } from "react";
import { DownloadSimpleIcon } from "@phosphor-icons/react/dist/ssr";
import Button from "./ui/Button";
import { toast } from "@/lib/use-toast";
import { exportIllumeAction } from "@/actions/exportIllume";

export default function ExportIllumeButton({ repo_id }: { repo_id: string }) {
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    setLoading(true);
    try {
      const content = await exportIllumeAction(repo_id);

      let repoName = "repo";
      const match = content.match(/^repo=(.+)$/m);
      if (match && match[1]) {
        repoName = match[1].trim();
      }

      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `${repoName}.illume`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast({
        title: "Export Success",
        description: `Successfully exported context to ${repoName}.illume`,
        variant: "success",
      });
    } catch (err) {
      console.error(err);
      toast({
        title: "Export Failed",
        description: "An error occurred while generating the .illume file.",
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      onClick={handleExport}
      size="sm"
      loading={loading}
      className="gap-1.5 shrink-0"
    >
      {!loading && <DownloadSimpleIcon weight="duotone" size={15} />}
      Export
    </Button>
  );
}
