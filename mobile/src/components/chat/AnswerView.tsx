/**
 * A run's answer and its sources.
 *
 * @module AnswerView
 *
 * Port of ``client/src/components/chat/AnswerView.tsx``. Citation keys in the
 * text are tappable once the run is done and open the source underneath.
 * Below the answer, the sources the answer cites and the other evidence the
 * run retrieved sit behind two disclosures.
 */

import { useMemo, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { AgentMarkdown } from "@/components/chat/AgentMarkdown";
import { CitationCard } from "@/components/CitationCard";
import {
  findCitation,
  keyOfCitation,
  partitionSources,
  shortKeyLabel,
  toSource,
} from "@/lib/agent/answer";
import type { RunState } from "@/lib/agent/reducer";
import type { Citation } from "@/lib/agent/types";

/** What a citation card needs to link out to GitHub. */
export interface RepoRef {
  url: string;
  commitSha: string | null;
  branch: string | null;
}

/** A tappable disclosure header. */
function Disclosure({
  label,
  open,
  onPress,
}: {
  label: string;
  open: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: open }}
      onPress={onPress}
      className="min-h-[36px] flex-row items-center gap-2"
    >
      <Text className="font-pixel text-xs uppercase tracking-[1.2px] text-muted-foreground">
        {label}
      </Text>
      <Text className="font-pixel text-[11px] text-muted-foreground">
        {open ? "▴" : "▾"}
      </Text>
    </Pressable>
  );
}

/**
 * Renders the answer of a run.
 *
 * @param props - The run and the repository's link data.
 * @returns The answer block, or null before any text has arrived.
 */
export function AnswerView({ run, repo }: { run: RunState; repo: RepoRef }) {
  const [opened, setOpened] = useState<Partial<Citation> | null>(null);
  const [showCited, setShowCited] = useState(false);
  const [showRetrieved, setShowRetrieved] = useState(false);
  const settled = run.status === "done";
  const streaming = run.status === "live" || run.status === "connecting";

  const parts = useMemo(
    () => partitionSources(run.answer, run.citations, run.evidenceKeys),
    [run.answer, run.citations, run.evidenceKeys],
  );

  if (!run.answer) return null;

  const card = (citation: Partial<Citation>, i: number, prefix: string) => (
    <CitationCard
      key={`${keyOfCitation(citation) ?? prefix}-${i}`}
      src={toSource(citation)}
      url={repo.url}
      commitSha={repo.commitSha}
      branch={repo.branch}
    />
  );

  return (
    <View testID="answer" className="gap-3">
      <AgentMarkdown
        text={run.answer}
        live={streaming}
        settled={settled}
        onOpenKey={(key) => {
          const found = findCitation(key, run.citations);
          if (found) setOpened(found);
        }}
      />

      {opened ? (
        <View testID="opened-citation">
          <CitationCard
            src={toSource(opened)}
            url={repo.url}
            commitSha={repo.commitSha}
            branch={repo.branch}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close source"
            onPress={() => setOpened(null)}
            className="mt-1 self-end px-2 py-1"
          >
            <Text className="font-pixel text-[11px] text-muted-foreground">
              Close
            </Text>
          </Pressable>
        </View>
      ) : null}

      {settled && parts.cited.length > 0 ? (
        <View>
          <Disclosure
            label={`Sources cited (${parts.cited.length})`}
            open={showCited}
            onPress={() => setShowCited((v) => !v)}
          />
          {showCited ? (
            <View className="mt-1">
              {parts.cited.map((citation, i) => card(citation, i, "c"))}
            </View>
          ) : null}
        </View>
      ) : null}

      {settled &&
      (parts.retrieved.length > 0 || parts.retrievedKeys.length > 0) ? (
        <View>
          <Disclosure
            label={`Also retrieved (${parts.retrieved.length + parts.retrievedKeys.length})`}
            open={showRetrieved}
            onPress={() => setShowRetrieved((v) => !v)}
          />
          {showRetrieved ? (
            <View className="mt-1">
              {parts.retrieved.map((citation, i) => card(citation, i, "r"))}
              {parts.retrievedKeys.length > 0 ? (
                <View className="flex-row flex-wrap gap-1.5">
                  {parts.retrievedKeys.slice(0, 40).map((key) => (
                    <Text
                      key={key}
                      className="rounded-sm border border-border px-1.5 py-0.5 font-pixel text-[10px] text-muted-foreground"
                    >
                      {shortKeyLabel(key)}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
