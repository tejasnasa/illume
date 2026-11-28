/**
 * The cards under a file in the explorer: neighbourhood, symbols, recent
 * changes, importers and imports.
 *
 * @module FileExtras
 *
 * Port of the detail grid in ``client/src/components/ui/FileDetailCard.tsx``
 * and of ``NeighbourhoodGraph.tsx``. The neighbourhood is a still
 * react-native-svg picture: the file in the middle, its importers on the left
 * and its imports on the right.
 */

import { useMemo } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import Svg, { Line, Rect } from "react-native-svg";

import { layoutNeighbourhood } from "@/lib/neighbourhood";
import { RISK_LEVELS, riskOf } from "@/lib/overview";
import { timeAgo } from "@/lib/timeAgo";
import { Eyebrow, Panel } from "@/ui/Panel";
import type { FileDetail, FileNode } from "@/types/explorer";

/** Symbol rows shown before the card says how many more there are. */
export const SYMBOL_ROWS = 8;
/** Rows each neighbour list shows before it says how many more there are. */
export const NEIGHBOUR_ROWS = 10;

const WIDTH = 320;
const HEIGHT = 200;

/** A bordered card with a pixel title row. */
function Section({
  title,
  testID,
  aside,
  children,
}: {
  title: string;
  testID?: string;
  aside?: string;
  children: React.ReactNode;
}) {
  return (
    <Panel testID={testID} className="mb-3 gap-3 p-4">
      <View className="flex-row items-center justify-between gap-2">
        <Eyebrow>{title}</Eyebrow>
        {aside ? (
          <Text className="font-pixel text-xs uppercase text-faint-foreground">{aside}</Text>
        ) : null}
      </View>
      {children}
    </Panel>
  );
}

/** A quiet line for a card with nothing to list. */
function EmptyLine({ children }: { children: string }) {
  return <Text className="font-pixel text-xs uppercase text-faint-foreground">{children}</Text>;
}

/** The file, its importers and its imports, drawn flat. */
export function NeighbourhoodCard({
  file,
  importers,
  imports,
}: {
  file: FileNode;
  importers: readonly FileNode[];
  imports: readonly FileNode[];
}) {
  const scene = useMemo(
    () => layoutNeighbourhood(file, importers, imports, WIDTH, HEIGHT),
    [file, importers, imports],
  );
  return (
    <Section title="Neighbourhood" testID="file-neighbourhood">
      <View
        accessible
        accessibilityRole="image"
        accessibilityLabel={`${file.label} is imported by ${importers.length} files and imports ${imports.length}`}
        style={{ height: 170, backgroundColor: "#060608" }}
      >
        <Svg width="100%" height="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
          {scene.lines.map((l, i) => (
            <Line
              key={i}
              x1={l.x1}
              y1={l.y1}
              x2={l.x2}
              y2={l.y2}
              stroke="#ffffff"
              strokeOpacity={0.14}
              strokeWidth={1}
            />
          ))}
          {scene.pixels.map((p) => (
            <Rect
              key={p.id}
              x={Math.round(p.x - p.size / 2)}
              y={Math.round(p.y - p.size / 2)}
              width={p.size}
              height={p.size}
              fill={p.color}
            />
          ))}
        </Svg>
        <Text className="absolute bottom-1 left-2 font-pixel text-[10px] uppercase text-faint-foreground">
          Imported by
        </Text>
        <Text className="absolute bottom-1 right-2 font-pixel text-[10px] uppercase text-faint-foreground">
          Imports
        </Text>
      </View>
    </Section>
  );
}

/** What the file defines. */
export function SymbolsCard({
  detail,
  loading,
  githubUrl,
  gitRef,
  path,
}: {
  detail: FileDetail | null;
  loading: boolean;
  githubUrl: string;
  gitRef: string;
  path: string;
}) {
  const symbols = detail?.symbols ?? [];
  const base = githubUrl.replace(/\/+$/, "");
  return (
    <Section title={`Symbols${detail ? ` · ${symbols.length}` : ""}`} testID="file-symbols">
      {loading ? (
        <EmptyLine>Loading symbols</EmptyLine>
      ) : symbols.length > 0 ? (
        <View className="gap-0.5">
          {symbols.slice(0, SYMBOL_ROWS).map((symbol, i) => (
            <Pressable
              key={`${symbol.name}-${symbol.start_line}-${i}`}
              testID="file-symbol-row"
              accessibilityRole="link"
              accessibilityLabel={`Open ${symbol.name} on GitHub`}
              onPress={() =>
                void Linking.openURL(
                  `${base}/blob/${gitRef}/${path}${symbol.start_line ? `#L${symbol.start_line}` : ""}`,
                )
              }
              className="flex-row items-center gap-3 rounded-sm px-1 py-2 active:bg-secondary"
            >
              <Text className="w-14 font-pixel text-[11px] uppercase text-accent">
                {symbol.kind}
              </Text>
              <Text numberOfLines={1} className="min-w-0 flex-1 font-pixel text-[13px] text-zinc-300">
                {symbol.name}
              </Text>
              {symbol.start_line != null ? (
                <Text className="font-pixel text-xs text-faint-foreground">L{symbol.start_line}</Text>
              ) : null}
            </Pressable>
          ))}
          {symbols.length > SYMBOL_ROWS ? (
            <Text className="px-1 py-1.5 font-pixel text-[11px] uppercase text-faint-foreground">
              and {symbols.length - SYMBOL_ROWS} more
            </Text>
          ) : null}
        </View>
      ) : (
        <EmptyLine>No functions or classes</EmptyLine>
      )}
    </Section>
  );
}

/** The latest commits that touched the file. */
export function RecentChangesCard({
  detail,
  loading,
  githubUrl,
}: {
  detail: FileDetail | null;
  loading: boolean;
  githubUrl: string;
}) {
  const commits = detail?.commits ?? [];
  const base = githubUrl.replace(/\/+$/, "");
  return (
    <Section title="Recent changes" testID="file-commits">
      {loading ? (
        <EmptyLine>Loading history</EmptyLine>
      ) : commits.length > 0 ? (
        <View className="gap-0.5">
          {commits.map((commit) => (
            <Pressable
              key={commit.hash}
              testID="file-commit-row"
              accessibilityRole="link"
              accessibilityLabel={`Open commit ${commit.hash.slice(0, 7)} on GitHub`}
              onPress={() => void Linking.openURL(`${base}/commit/${commit.hash}`)}
              className="flex-row items-start gap-3 rounded-sm px-1 py-2 active:bg-secondary"
            >
              <Text className="pt-0.5 font-pixel text-xs text-accent">{commit.hash.slice(0, 7)}</Text>
              <View className="min-w-0 flex-1 gap-1">
                <Text numberOfLines={1} className="text-sm text-zinc-300">
                  {commit.title || "No message"}
                </Text>
                <Text className="font-pixel text-[11px] uppercase text-faint-foreground">
                  Commit · {commit.author} · {timeAgo(commit.at)}
                </Text>
              </View>
            </Pressable>
          ))}
        </View>
      ) : (
        <EmptyLine>No commits in the analysed history</EmptyLine>
      )}
    </Section>
  );
}

/** A list of connected files; each row selects that file. */
export function NeighbourListCard({
  title,
  testID,
  files,
  empty,
  onSelectPath,
}: {
  title: string;
  testID: string;
  files: readonly FileNode[];
  empty: string;
  onSelectPath: (path: string) => void;
}) {
  const shown = files.slice(0, NEIGHBOUR_ROWS);
  return (
    <Section title={`${title} · ${files.length}`} testID={testID}>
      {files.length === 0 ? (
        <EmptyLine>{empty}</EmptyLine>
      ) : (
        <View className="gap-0.5">
          {shown.map((f) => {
            const color = RISK_LEVELS.find((r) => r.key === riskOf(f.criticality))!.color;
            return (
              <Pressable
                key={f.path}
                testID={`neighbour-${f.path}`}
                accessibilityRole="button"
                accessibilityLabel={`Open ${f.path}`}
                onPress={() => onSelectPath(f.path)}
                className="flex-row items-center gap-2.5 rounded-sm px-1 py-2 active:bg-secondary"
              >
                <View style={{ width: 6, height: 6, backgroundColor: color }} />
                <Text numberOfLines={1} className="min-w-0 flex-1 font-pixel text-[13px] text-zinc-300">
                  {f.path}
                </Text>
              </Pressable>
            );
          })}
          {files.length > shown.length ? (
            <Text className="px-1 py-1.5 font-pixel text-[11px] uppercase text-faint-foreground">
              and {files.length - shown.length} more
            </Text>
          ) : null}
        </View>
      )}
    </Section>
  );
}
