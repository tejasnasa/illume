/**
 * One-tap export of the compressed ``.illume`` context file.
 *
 * @module ExportIllumeButton
 *
 * Port of ``client/src/components/ExportIllumeButton.tsx``. The web version
 * hands the text to an ``<a download>``; a phone has no download folder,
 * so the bundle is written into the cache directory and the system share
 * sheet is opened for it -- the same gesture the user already knows from
 * every other app that offers "share this file".
 *
 * The file lands in the **cache** directory on purpose: the export is a
 * derived artefact the server can produce again at any time, and the system
 * is free to reclaim cached files when the device runs low on space.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Text,
  View,
} from "react-native";
import { File, Paths } from "expo-file-system";
import { isAvailableAsync, shareAsync } from "expo-sharing";

import { exportRepositoryIllume, type SettingsRequestOptions } from "@/api/settings";
import { colors } from "@/theme/tokens";

/**
 * The file extension the export carries.
 */
const EXPORT_EXTENSION = ".illume";

/**
 * Props for the ExportIllumeButton component.
 */
export interface ExportIllumeButtonProps {
  /** The repository's UUID. */
  repoId: string;
  /**
   * The repository's name, used for the file name when the bundle carries
   * none.
   */
  repoName?: string;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
  /** The button's label. */
  label?: string;
  /** The button's test id. */
  testID?: string;
}

/**
 * Pull the repository name out of a bundle.
 *
 * The bundle's meta block opens with a ``repo=`` line. The web version uses
 * it for the download's file name; this does the same.
 *
 * @param content - The bundle's text.
 * @returns The repository name, or an empty string when there is none.
 */
export function repoNameFromBundle(content: string): string {
  const match = content.match(/^repo=(.+)$/m);
  if (match && match[1]) return match[1].trim();
  return "";
}

/**
 * Turn a name into something a file system will accept.
 *
 * The name comes from the bundle, and a bundle can carry anything the
 * repository was called -- including a slash, which would otherwise point
 * the write at a directory that does not exist.
 *
 * @param name - The raw name.
 * @returns The sanitised file name, without the extension.
 */
export function safeFileName(name: string): string {
  const cleaned = name.trim().replace(/[^a-zA-Z0-9._-]+/g, "-");
  const trimmed = cleaned.replace(/^-+|-+$/g, "");
  return trimmed.length > 0 ? trimmed : "repo";
}

/**
 * Export a repository's context and offer it to the share sheet.
 *
 * @param props - The repository, the transport overrides and the label.
 * @returns The rendered button.
 */
export function ExportIllumeButton({
  repoId,
  repoName,
  options,
  label = "Export",
  testID = "export-illume",
}: ExportIllumeButtonProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch the bundle, write it to the cache directory, and share it.
   */
  const handleExport = async () => {
    setError(null);
    setIsExporting(true);
    try {
      const content = await exportRepositoryIllume(repoId, options);

      const name = safeFileName(repoNameFromBundle(content) || repoName || "repo");
      const file = new File(Paths.cache, `${name}${EXPORT_EXTENSION}`);
      file.create({ overwrite: true });
      file.write(content);

      const available = await isAvailableAsync();
      if (!available) {
        setError("Sharing is not available on this device.");
        return;
      }

      await shareAsync(file.uri, {
        mimeType: "text/plain",
        dialogTitle: `${name}${EXPORT_EXTENSION}`,
      });
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : "Failed to export repository data",
      );
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <View>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: isExporting }}
        disabled={isExporting}
        onPress={() => {
          void handleExport();
        }}
        className="min-h-[44px] items-center justify-center rounded bg-primary px-4 active:opacity-80"
      >
        {isExporting ? (
          <ActivityIndicator size="small" color={colors.primaryForeground} />
        ) : (
          <Text className="text-[13px] font-semibold text-primary-foreground">
            {label}
          </Text>
        )}
      </Pressable>

      {error ? (
        <Text
          testID={`${testID}-error`}
          className="mt-2 text-xs text-destructive"
        >
          {error}
        </Text>
      ) : null}
    </View>
  );
}

export default ExportIllumeButton;
