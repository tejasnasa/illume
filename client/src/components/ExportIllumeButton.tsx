/**
 * One-click download of the compressed `.illume` context file.
 * @module ExportIllumeButton
 */
"use client";

import { exportIllumeAction } from "@/actions/exportIllume";
import { DownloadSimpleIcon } from "@phosphor-icons/react/dist/ssr";
import { useState } from "react";
import Button from "./ui/Button";

/**
 * Exports repository context and saves it as a local file.
 *
 * @param repo_id - ID of the repository to export.
 * @returns Button that triggers the export download.
 */
export default function ExportIllumeButton({ repo_id }: { repo_id: string }) {
  const [loading, setLoading] = useState(false);

  /** Fetches export text and saves it via a temporary anchor download. */
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
    } catch (err) {
      console.error(err);
      alert(err);
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
