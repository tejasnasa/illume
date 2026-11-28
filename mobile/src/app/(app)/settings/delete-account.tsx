/**
 * Delete the account, confirmed by typing its email.
 *
 * @module DeleteAccountScreen
 *
 * Port of ``client/src/components/DeleteAccount.tsx``. The server removes
 * every repository, conversation and token the account owns; on success the
 * session is cleared and the app returns to the sign-in screen.
 */

import { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";

import { deleteAccount } from "@/api/account";
import { useAuth } from "@/hooks/useAuth";
import { emailConfirms } from "@/lib/accountSettings";
import { colors } from "@/theme/tokens";
import { Button } from "@/ui/Button";
import { Eyebrow, Panel } from "@/ui/Panel";
import { SettingsHeader } from "@/ui/SettingsHeader";

/**
 * Draw the screen.
 *
 * @returns The delete-account screen.
 */
export default function DeleteAccountScreen() {
  const { user, signOut } = useAuth();
  const [typed, setTyped] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const email = user?.email ?? "";
  const confirmed = emailConfirms(typed, email);

  const handleDelete = async () => {
    if (!confirmed) return;
    setPending(true);
    setError(null);
    try {
      await deleteAccount(typed.trim());
      await signOut();
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message
          ? cause.message
          : "Could not delete the account. Try again.",
      );
      setPending(false);
    }
  };

  return (
    <View className="flex-1" testID="delete-account-screen">
      <SettingsHeader title="Delete account" />
      <ScrollView contentContainerStyle={{ padding: 16 }} keyboardShouldPersistTaps="handled">
        <Panel className="gap-3 border-destructive/40 p-4">
          <Eyebrow>Danger zone</Eyebrow>
          <Text className="text-sm leading-[20px] text-zinc-300">
            Deleting your account removes every repository, chat and token. It
            cannot be undone.
          </Text>
          <Text className="text-xs text-muted-foreground">
            Type <Text className="font-pixel text-foreground">{email}</Text> to confirm.
          </Text>
          <TextInput
            testID="delete-account-email"
            accessibilityLabel="Type your email to confirm"
            value={typed}
            onChangeText={setTyped}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            placeholder={email}
            placeholderTextColor={colors.faintForeground}
            className="min-h-[44px] rounded-sm border border-input bg-background px-3 text-sm text-foreground"
          />
          {error ? (
            <Text testID="delete-account-error" className="text-xs text-destructive">
              {error}
            </Text>
          ) : null}
          <Button
            testID="delete-account-confirm"
            variant="danger"
            disabled={!confirmed}
            loading={pending}
            onPress={() => void handleDelete()}
          >
            Delete my account
          </Button>
        </Panel>
      </ScrollView>
    </View>
  );
}
