/**
 * The view shown for a repository that is not ready yet.
 *
 * @module RepoStatusView
 *
 * The web client replaces the whole repository page with its live ingest
 * view while a repository is being indexed. That view arrives with the
 * live stream, so this is the static half of it: the same headline and
 * stage names, driven by the coarse status instead of by stream frames.
 *
 * The copy is the web client's, verbatim where it exists:
 *
 * - "Queued — waiting for a worker" for a repository no worker has
 *   claimed.
 * - The stage name for a repository in flight ("Parse files", "Generate
 *   Embeddings", ...).
 * - "Failed, retrying…" while the pipeline is still inside its retry
 *   window, and "Ingestion failed" once it is not.
 */

import { ActivityIndicator, ScrollView, Text, View } from "react-native";

import {
  PIPELINE_STAGES,
  isFailedStatus,
  stageStatesFromStatus,
  statusDescription,
  statusHeadline,
  type StageState,
} from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/** Props for the {@link RepoStatusView} component. */
export interface RepoStatusViewProps {
  /** The repository's ingestion status. */
  status: string;
  /**
   * How long the repository has been in the failed state, in milliseconds.
   * Inside the retry grace period the pipeline is probably still retrying.
   */
  failureAgeMs?: number;
  /** The repository's ``owner/name``, shown under the headline. */
  repoLabel?: string;
  /** The branch being ingested, if known. */
  branch?: string | null;
  /** The commit being ingested, if known. */
  commitSha?: string | null;
  /** Test hook. */
  testID?: string;
}

/**
 * The colour a stage is drawn in.
 *
 * @param state - The stage's state.
 * @returns The colour token name.
 */
function stageTone(state: StageState): string {
  if (state === "done") return colors.success;
  if (state === "active") return colors.chart1;
  return colors.mutedForeground;
}

/**
 * Render the not-ready state of a repository.
 *
 * @param props - The repository's status and identity.
 * @returns The rendered view.
 */
export function RepoStatusView({
  status,
  failureAgeMs,
  repoLabel,
  branch,
  commitSha,
  testID = "repo-status-view",
}: RepoStatusViewProps) {
  const failed = isFailedStatus(status);
  const headline = statusHeadline(status, failureAgeMs);
  const description = statusDescription(status);
  const stageStates = stageStatesFromStatus(status);
  const shortSha = commitSha ? commitSha.substring(0, 7) : null;

  return (
    <ScrollView
      testID={testID}
      className="flex-1 bg-background"
      contentContainerClassName="p-4"
    >
      <View className="mb-4 rounded border border-border p-4">
        <View className="flex-row items-center">
          {failed ? (
            <Text className="mr-2 text-lg text-destructive">⚠</Text>
          ) : (
            <ActivityIndicator
              size="small"
              color={colors.chart1}
              style={styles.spinner}
            />
          )}
          <Text
            testID="repo-status-headline"
            className={`text-lg font-bold uppercase tracking-wide ${
              failed ? "text-destructive" : "text-chart-1"
            }`}
          >
            {headline}
          </Text>
        </View>

        <Text className="mt-2 text-[13px] leading-[18px] text-muted-foreground">
          {description}
        </Text>

        {repoLabel || branch ? (
          <Text className="mt-3 font-mono text-[11px] text-muted-foreground">
            {repoLabel ?? ""}
            {branch ? ` · ${branch}` : ""}
            {shortSha ? ` @${shortSha}` : ""}
          </Text>
        ) : null}
      </View>

      {failed ? null : (
        <View className="rounded border border-border p-4">
          <Text className="mb-3 text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground opacity-60">
            Pipeline
          </Text>

          {PIPELINE_STAGES.map((stage, index) => {
            const state = stageStates[stage.id] ?? "pending";
            const isLast = index === PIPELINE_STAGES.length - 1;
            return (
              <View key={stage.id} className="flex-row items-start">
                <View className="items-center" style={styles.rail}>
                  <View
                    style={[styles.dot, { backgroundColor: stageTone(state) }]}
                  />
                  {isLast ? null : <View style={styles.connector} />}
                </View>

                <View className="flex-1 pb-3">
                  <Text
                    style={{
                      color:
                        state === "pending"
                          ? colors.mutedForeground
                          : stageTone(state),
                      fontWeight: state === "active" ? "700" : "400",
                    }}
                    className="text-[13px]"
                  >
                    {stage.label}
                  </Text>
                </View>
              </View>
            );
          })}
        </View>
      )}
    </ScrollView>
  );
}

// The pipeline rail is a column of dots joined by hairlines. NativeWind has
// no pseudo-element or border-collapse for this, so the two pieces are
// inline styles with hardcoded colours.
const styles = {
  rail: { width: 16, alignItems: "center" },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 4,
  },
  connector: {
    width: 1,
    flex: 1,
    minHeight: 12,
    backgroundColor: "rgba(255, 255, 255, 0.12)",
  },
  spinner: { marginRight: 8 },
} as const;

export default RepoStatusView;
