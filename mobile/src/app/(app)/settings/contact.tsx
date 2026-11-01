/**
 * Contact screen.
 *
 * @module ContactScreen
 *
 * Port of the web client's contact page
 * (``client/src/app/contact/page.tsx`` and ``client/src/components/ContactForm.tsx``).
 * On a phone the form is its own screen so the keyboard has room and the
 * reader is not scrolling a landing page to reach it.
 *
 * The identity fields are prefilled from the signed-in profile. They are a
 * convenience only -- they are resubmitted as ordinary form values, so
 * they are no more trustworthy than anything typed by hand.
 */

import { Pressable, ScrollView, Text, View } from "react-native";
import { router } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ContactForm } from "@/components/ContactForm";
import { useAuth } from "@/hooks/useAuth";

/**
 * Draw the contact screen.
 *
 * @returns The rendered screen.
 */
export default function ContactScreen() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();

  return (
    <View className="flex-1 bg-background" style={{ paddingTop: insets.top }}>
      <View className="flex-row items-center border-b border-border px-3 py-2">
        <Pressable
          testID="settings-contact-back"
          accessibilityRole="button"
          accessibilityLabel="Back to settings"
          onPress={() => router.back()}
          hitSlop={8}
          className="mr-2 rounded px-2 py-1 active:bg-secondary"
        >
          <Text className="text-lg text-foreground">←</Text>
        </Pressable>
        <Text className="flex-1 text-base font-medium text-foreground">
          Contact
        </Text>
      </View>

      <ScrollView
        testID="settings-contact-scroll"
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: 16,
          paddingBottom: insets.bottom + 32,
        }}
      >
        <Text className="mb-4 text-[13px] text-muted-foreground">
          Tell us what happened, what you expected, and how to reproduce it.
        </Text>

        <ContactForm defaultName={user?.name} defaultEmail={user?.email} />
      </ScrollView>
    </View>
  );
}
