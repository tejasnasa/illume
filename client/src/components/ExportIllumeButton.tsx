/**
 * One-click download of the compressed `.illume` context file.
 * @module ExportIllumeButton
 */
"use client";

import { exportIllumeAction } from "@/actions/exportIllume";
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
  const [error, setError] = useState<string | null>(null);

  /** Fetches export text and saves it via a temporary anchor download. */
  const handleExport = async () => {
    setLoading(true);
    setError(null);
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
      setError(err instanceof Error ? err.message : "Export failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <span className="flex flex-col items-end gap-1.5">
      <Button onClick={handleExport} size="sm" variant="ghost" loading={loading} className="shrink-0">
        {!loading && <span aria-hidden="true">↓</span>}
        Export
      </Button>
      {error && (
        <span role="alert" className="text-xs text-red-300">
          {error}
        </span>
      )}
    </span>
  );
}
