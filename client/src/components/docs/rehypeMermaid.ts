/**
 * Rehype plugin that lifts ```mermaid fences out of the normal code-block path.
 *
 * It replaces each `<pre><code class="language-mermaid">` with a `<mermaid-diagram>`
 * element whose only child is the source text, which `DocsMarkdown` maps to the
 * client-side `Mermaid` component. Must run before the syntax highlighter, which would
 * otherwise tokenise the diagram source into spans.
 * @module RehypeMermaid
 */
import type { Element, Root, RootContent } from "hast";

/** Tag the plugin emits; `DocsMarkdown` maps it to the `Mermaid` component. */
export const MERMAID_TAG = "mermaid-diagram";

function textOf(node: RootContent): string {
  if (node.type === "text") return node.value;
  if (node.type === "element") return node.children.map(textOf).join("");
  return "";
}

function isMermaidFence(node: Element): boolean {
  if (node.tagName !== "pre") return false;
  const code = node.children[0];
  if (!code || code.type !== "element" || code.tagName !== "code") return false;
  const classes = code.properties?.className;
  return Array.isArray(classes) && classes.includes("language-mermaid");
}

function transform(parent: Root | Element): void {
  parent.children = parent.children.map((child) => {
    if (child.type !== "element") return child;
    if (isMermaidFence(child)) {
      return {
        type: "element",
        tagName: MERMAID_TAG,
        properties: {},
        children: [{ type: "text", value: textOf(child).replace(/\n$/, "") }],
      } satisfies Element;
    }
    transform(child);
    return child;
  });
}

/** Unified plugin; takes no options. */
export function rehypeMermaid() {
  return (tree: Root) => transform(tree);
}
