/**
 * Rail geometry for the commit timeline.
 *
 * @module GitGraphLayout
 *
 * Port of the layout half of ``client/src/components/GitGraph.tsx``. The
 * web component computed rail assignments, bezier links and node positions
 * inline during render; here they are a pure function over the commit list
 * so the geometry can be unit-tested without mounting a view.
 *
 * The algorithm threads parent SHAs down a set of "active tracks" to work
 * out which rail each commit sits on: a commit takes the rail that already
 * holds its SHA, otherwise the first free rail, otherwise a new rail is
 * opened. Each commit's first parent inherits its rail; any further
 * parents (merge commits) look for a free rail to branch onto.
 */

/**
 * Rail colours, cycled by rail index.
 *
 * Copied from the web component so the timeline reads the same on both
 * platforms. These are literal hex values rather than theme tokens: the
 * palette is categorical (one hue per rail), not semantic, and a theme
 * slot per rail would not survive the light/dark split.
 */
export const RAIL_COLORS = [
  "#a78bfa",
  "#34d399",
  "#22d3ee",
  "#fbbf24",
  "#f43f5e",
  "#60a5fa",
] as const;

/** Horizontal distance between two adjacent rails, in points. */
export const COLUMN_WIDTH = 18;

/** Height of one commit row, in points. */
export const ROW_HEIGHT = 64;

/** Radius of a commit node, in points. */
export const NODE_RADIUS = 5;

/** Horizontal padding inside the rail area, in points. */
export const PADDING_X = 10;

/**
 * Vertical offset of the first node from the top of the timeline.
 *
 * Half a row, so a node sits in the vertical centre of its row -- which
 * is what keeps the rail and the commit card visually aligned.
 */
export const PADDING_Y = ROW_HEIGHT / 2;

/**
 * Map a rail index to a stable colour, cycling the palette.
 *
 * @param trackIndex - Zero-based rail column.
 * @returns Hex colour for the rail.
 */
export function getRailColor(trackIndex: number): string {
  return RAIL_COLORS[trackIndex % RAIL_COLORS.length];
}

/** A bezier link drawn between two commits. */
export interface GitGraphLink {
  /** SVG path data for the link. */
  path: string;
  /** Stroke colour, taken from the source commit's rail. */
  stroke: string;
}

/** A commit node drawn on the rail. */
export interface GitGraphNode {
  /** X coordinate of the node centre. */
  x: number;
  /** Y coordinate of the node centre. */
  y: number;
  /** The rail the node sits on. */
  column: number;
  /** The commit's SHA, so the renderer can match it to a row. */
  sha: string;
}

/** Everything the renderer needs to draw the rail area. */
export interface GitGraphLayout {
  /** Rail index per commit, in commit order. */
  tracks: number[];
  /** Number of rails the timeline occupies. */
  railCount: number;
  /** Bezier links between commits and their parents. */
  links: GitGraphLink[];
  /** Commit nodes, in commit order. */
  nodes: GitGraphNode[];
  /** Width of the rail area, in points. */
  width: number;
  /** Height of the rail area, in points. */
  height: number;
}

/**
 * Compute the rail layout for a list of commits.
 *
 * @param commits - Commits, newest first, as the proxy returns them.
 * @returns The rail assignment, links and node positions.
 */
export function buildGitGraphLayout(
  commits: readonly { sha: string; parents: string[] }[],
): GitGraphLayout {
  const commitMap = new Map<string, number>();
  commits.forEach((commit, index) => commitMap.set(commit.sha, index));

  const tracks: number[] = [];
  const activeTracks: (string | null)[] = [];

  // Assign each commit a rail, threading parent SHAs down the rails.
  for (let row = 0; row < commits.length; row++) {
    const commit = commits[row];
    const sha = commit.sha;

    let column = activeTracks.indexOf(sha);
    if (column === -1) {
      column = activeTracks.indexOf(null);
      if (column === -1) {
        column = activeTracks.length;
        activeTracks.push(sha);
      } else {
        activeTracks[column] = sha;
      }
    }
    tracks[row] = column;

    // A SHA can only occupy one rail; blank out any duplicate.
    for (let i = 0; i < activeTracks.length; i++) {
      if (i !== column && activeTracks[i] === sha) {
        activeTracks[i] = null;
      }
    }

    activeTracks[column] = null;

    if (commit.parents.length > 0) {
      activeTracks[column] = commit.parents[0];
      for (let p = 1; p < commit.parents.length; p++) {
        const parentSha = commit.parents[p];
        let parentColumn = activeTracks.indexOf(parentSha);
        if (parentColumn === -1) {
          parentColumn = activeTracks.indexOf(null);
          if (parentColumn === -1) {
            activeTracks.push(parentSha);
          } else {
            activeTracks[parentColumn] = parentSha;
          }
        }
      }
    }
  }

  const railCount = Math.max(activeTracks.length, 1);

  const getX = (column: number) => column * COLUMN_WIDTH + PADDING_X;
  const getY = (row: number) => row * ROW_HEIGHT + PADDING_Y;

  const links: GitGraphLink[] = [];
  commits.forEach((commit, row) => {
    const column = tracks[row];
    const x1 = getX(column);
    const y1 = getY(row);
    const stroke = getRailColor(column);

    commit.parents.forEach((parentSha) => {
      const parentRow = commitMap.get(parentSha);
      if (parentRow !== undefined) {
        const x2 = getX(tracks[parentRow]);
        const y2 = getY(parentRow);

        const dy = y2 - y1;
        const cpY1 = y1 + dy * 0.45;
        const cpY2 = y2 - dy * 0.45;
        links.push({
          path: `M ${x1} ${y1} C ${x1} ${cpY1}, ${x2} ${cpY2}, ${x2} ${y2}`,
          stroke,
        });
      } else {
        // The parent is outside the fetched window; draw a stub so the rail
        // does not appear to dead-end at the node.
        links.push({
          path: `M ${x1} ${y1} L ${x1} ${y1 + ROW_HEIGHT}`,
          stroke,
        });
      }
    });
  });

  const nodes: GitGraphNode[] = commits.map((commit, row) => ({
    x: getX(tracks[row]),
    y: getY(row),
    column: tracks[row],
    sha: commit.sha,
  }));

  return {
    tracks,
    railCount,
    links,
    nodes,
    width: railCount * COLUMN_WIDTH + PADDING_X * 2,
    height: commits.length * ROW_HEIGHT,
  };
}
