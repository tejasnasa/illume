/**
 * MCP access tokens and the snippets that connect an AI tool.
 *
 * @module McpSettingsScreen
 *
 * Port of ``client/src/components/McpSettings.tsx``. A created token's
 * plaintext lives only in component state while the notice is on screen; it
 * is shared through the system share sheet and never stored. Revoking asks
 * for confirmation first.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Share,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  createMcpToken,
  listMcpTokens,
  revokeMcpToken,
} from "@/api/account";
import { resolveBackendUrl } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import {
  TOKEN_EXPIRIES,
  TOKEN_PLACEHOLDER,
  buildSnippet,
  type SnippetTab,
} from "@/lib/accountSettings";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import type { McpToken } from "@/types/mcp";
import { Button } from "@/ui/Button";
import { Eyebrow, Panel } from "@/ui/Panel";
import { SettingsHeader } from "@/ui/SettingsHeader";

const TABS: { id: SnippetTab; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "cursor", label: "Cursor" },
  { id: "vscode", label: "VS Code" },
  { id: "codex", label: "Codex" },
];

/**
 * Draw the screen.
 *
 * @returns The MCP settings screen.
 */
export default function McpSettingsScreen() {
  const { user } = useAuth();
  const [tokens, setTokens] = useState<McpToken[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<30 | 90 | null>(90);
  const [fresh, setFresh] = useState<string | null>(null);
  const [tab, setTab] = useState<SnippetTab>("claude-code");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listMcpTokens()
      .then((list) => {
        if (!cancelled) setTokens(list);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const url = `${resolveBackendUrl()}/mcp`;

  const create = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Give the token a name.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const { token, ...created } = await createMcpToken({
        name: trimmed,
        expiresInDays: expiry,
      });
      setTokens((current) => [created, ...current]);
      setFresh(token);
      setName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create token.");
    } finally {
      setPending(false);
    }
  }, [name, expiry]);

  const revoke = useCallback((token: McpToken) => {
    Alert.alert(
      "Revoke token",
      `"${token.name}" stops working immediately.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: () => {
            void revokeMcpToken(token.id)
              .then(() =>
                setTokens((current) => current.filter((item) => item.id !== token.id)),
              )
              .catch((cause: unknown) =>
                setError(
                  cause instanceof Error ? cause.message : "Failed to revoke token.",
                ),
              );
          },
        },
      ],
    );
  }, []);

  if (user && user.mcp_enabled === false) {
    return (
      <View className="flex-1">
        <SettingsHeader title="MCP" />
        <Text className="p-4 text-sm text-muted-foreground">
          The MCP endpoint is switched off on this server.
        </Text>
      </View>
    );
  }

  const snippet = buildSnippet(tab, url, fresh ?? TOKEN_PLACEHOLDER);

  return (
    <View className="flex-1" testID="mcp-settings-screen">
      <SettingsHeader title="MCP" />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 16 }} keyboardShouldPersistTaps="handled">
        {fresh ? (
          <Panel className="gap-2 border-accent/40 p-4" testID="mcp-fresh-token">
            <Eyebrow>New token</Eyebrow>
            <Text selectable className="font-pixel text-xs text-foreground">
              {fresh}
            </Text>
            <Text className="text-xs text-muted-foreground">
              Copy your token now, you will not see this again.
            </Text>
            <View className="flex-row gap-2">
              <Button
                size="sm"
                variant="ghost"
                testID="mcp-share-token"
                onPress={() => void Share.share({ message: fresh })}
              >
                Share token
              </Button>
              <Button size="sm" variant="ghost" onPress={() => setFresh(null)}>
                Done
              </Button>
            </View>
          </Panel>
        ) : null}

        <Panel className="gap-2 p-4">
          <Eyebrow>Tokens · {tokens.length}</Eyebrow>
          {!loaded ? <ActivityIndicator color={colors.mutedForeground} /> : null}
          {loaded && tokens.length === 0 ? (
            <Text className="text-xs text-muted-foreground">
              {loadFailed
                ? "Your tokens could not be loaded."
                : "No tokens yet. Create one below."}
            </Text>
          ) : null}
          {tokens.map((token) => (
            <View
              key={token.id}
              testID={`mcp-token-${token.id}`}
              className="flex-row items-center justify-between border-t border-border py-2"
            >
              <View className="flex-1">
                <Text className="text-sm text-foreground">{token.name}</Text>
                <Text className="font-pixel text-[11px] text-muted-foreground">
                  ilm_{token.prefix}… ·{" "}
                  {token.last_used_at ? `used ${timeAgo(token.last_used_at)}` : "never used"}
                  {token.expires_at ? ` · expires ${timeAgo(token.expires_at)}` : ""}
                </Text>
              </View>
              <Pressable
                testID={`mcp-revoke-${token.id}`}
                accessibilityRole="button"
                onPress={() => revoke(token)}
                className="min-h-[40px] justify-center px-2"
              >
                <Text className="font-pixel text-[11px] uppercase text-destructive">
                  Revoke
                </Text>
              </Pressable>
            </View>
          ))}
        </Panel>

        <Panel className="gap-3 p-4">
          <Eyebrow>Create a token</Eyebrow>
          <TextInput
            testID="mcp-token-name"
            accessibilityLabel="Token name"
            value={name}
            onChangeText={(text) => {
              setName(text);
              setError(null);
            }}
            placeholder="Laptop"
            placeholderTextColor={colors.mutedForeground}
            maxLength={80}
            className="min-h-[44px] rounded-sm border border-input bg-background px-3 text-sm text-foreground"
          />
          <View className="flex-row gap-2">
            {TOKEN_EXPIRIES.map((option) => (
              <Pressable
                key={option.label}
                testID={`mcp-expiry-${option.days ?? "never"}`}
                accessibilityState={{ selected: option.days === expiry }}
                onPress={() => setExpiry(option.days)}
                className={`min-h-[36px] justify-center rounded-sm border px-3 ${
                  option.days === expiry ? "border-accent bg-accent/10" : "border-input"
                }`}
              >
                <Text className="font-pixel text-[11px] uppercase text-zinc-300">
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>
          {error ? (
            <Text testID="mcp-error" className="text-xs text-destructive">
              {error}
            </Text>
          ) : null}
          <Button testID="mcp-create" loading={pending} onPress={() => void create()}>
            Create token
          </Button>
        </Panel>

        <Panel className="gap-3 p-4">
          <Eyebrow>Connect a tool</Eyebrow>
          <View className="flex-row flex-wrap gap-2">
            {TABS.map((entry) => (
              <Pressable
                key={entry.id}
                testID={`mcp-tab-${entry.id}`}
                accessibilityState={{ selected: entry.id === tab }}
                onPress={() => setTab(entry.id)}
                className={`min-h-[36px] justify-center rounded-sm border px-3 ${
                  entry.id === tab ? "border-accent bg-accent/10" : "border-input"
                }`}
              >
                <Text className="font-pixel text-[11px] uppercase text-zinc-300">
                  {entry.label}
                </Text>
              </Pressable>
            ))}
          </View>
          <Text
            selectable
            testID="mcp-snippet"
            className="rounded-sm border border-border bg-background p-3 font-pixel text-[11px] leading-[17px] text-zinc-300"
          >
            {snippet}
          </Text>
          <Button
            size="sm"
            variant="ghost"
            testID="mcp-share-snippet"
            onPress={() => void Share.share({ message: snippet })}
          >
            Share snippet
          </Button>
        </Panel>
      </ScrollView>
    </View>
  );
}
