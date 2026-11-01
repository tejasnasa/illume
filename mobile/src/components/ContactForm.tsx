/**
 * Contact form panel: category, identity, and message.
 *
 * @module ContactForm
 *
 * Port of ``client/src/components/ContactForm.tsx``. The web version
 * renders the category as a ``<select>``; on a phone that becomes a list of
 * radio rows inside a modal, which is the idiom that behaves the same on
 * both platforms.
 *
 * The form shows a single error banner rather than one per field: it is
 * short enough that a reader does not want to hunt for which box is red.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";

import { useContactForm } from "@/hooks/useContactForm";
import type { SettingsRequestOptions } from "@/api/settings";
import { contactCategories } from "@/types/validators";
import { colors } from "@/theme/tokens";

/**
 * Props for the ContactForm component.
 */
export interface ContactFormProps {
  /** Name to prefill, when the visitor is signed in. */
  defaultName?: string;
  /** Email to prefill, when the visitor is signed in. */
  defaultEmail?: string;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
}

/**
 * Draw the contact form.
 *
 * @param props - The prefilled identity and the transport overrides.
 * @returns The rendered form.
 */
export function ContactForm({
  defaultName,
  defaultEmail,
  options,
}: ContactFormProps) {
  const {
    category,
    setCategory,
    name,
    setName,
    email,
    setEmail,
    message,
    setMessage,
    error,
    successMessage,
    isSubmitting,
    onSubmit,
  } = useContactForm({ name: defaultName, email: defaultEmail, options });

  const [pickerOpen, setPickerOpen] = useState(false);

  const activeCategory = contactCategories.find((entry) => entry.value === category);

  return (
    <View testID="contact-form" className="rounded border border-border bg-card p-4">
      <Text className="mb-1 text-[13px] font-medium text-foreground">
        What is this about?
      </Text>
      <Pressable
        testID="contact-form-category"
        accessibilityRole="button"
        accessibilityLabel="Choose a category"
        accessibilityState={{ expanded: pickerOpen }}
        onPress={() => setPickerOpen(true)}
        className="min-h-[44px] flex-row items-center justify-between rounded border border-border bg-secondary/20 px-3 active:bg-secondary"
      >
        <Text
          className={`text-sm ${
            activeCategory ? "text-foreground" : "text-muted-foreground"
          }`}
        >
          {activeCategory?.label ?? "Select a category"}
        </Text>
        <Text className="text-xs text-muted-foreground">▾</Text>
      </Pressable>

      <Text className="mb-1 mt-4 text-[13px] font-medium text-foreground">
        Name
      </Text>
      <TextInput
        testID="contact-form-name"
        accessibilityLabel="Name"
        value={name}
        onChangeText={setName}
        placeholder="Tejas Nasa"
        placeholderTextColor={colors.mutedForeground}
        className="min-h-[44px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />

      <Text className="mb-1 mt-4 text-[13px] font-medium text-foreground">
        Email
      </Text>
      <TextInput
        testID="contact-form-email"
        accessibilityLabel="Email"
        value={email}
        onChangeText={setEmail}
        placeholder="you@example.com"
        placeholderTextColor={colors.mutedForeground}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
        className="min-h-[44px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />

      <Text className="mb-1 mt-4 text-[13px] font-medium text-foreground">
        Message
      </Text>
      <TextInput
        testID="contact-form-message"
        accessibilityLabel="Message"
        value={message}
        onChangeText={setMessage}
        placeholder="What happened, what you expected, and how to reproduce it."
        placeholderTextColor={colors.mutedForeground}
        multiline
        numberOfLines={6}
        textAlignVertical="top"
        className="min-h-[120px] rounded border border-border bg-secondary/20 px-3 py-2 text-sm text-foreground"
      />

      {error ? (
        <View
          testID="contact-form-error"
          className="mx-0 mb-3 mt-4 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
      ) : null}

      {successMessage ? (
        <Text
          testID="contact-form-success"
          accessibilityRole="text"
          className="mt-4 text-[13px] text-success"
        >
          {successMessage}
        </Text>
      ) : null}

      <Pressable
        testID="contact-form-submit"
        accessibilityRole="button"
        accessibilityLabel="Send message"
        accessibilityState={{ disabled: isSubmitting }}
        disabled={isSubmitting}
        onPress={() => {
          void onSubmit();
        }}
        className="mt-4 min-h-[44px] items-center justify-center rounded bg-primary active:opacity-80"
      >
        {isSubmitting ? (
          <ActivityIndicator size="small" color={colors.primaryForeground} />
        ) : (
          <Text className="text-[13px] font-semibold text-primary-foreground">
            Send message
          </Text>
        )}
      </Pressable>

      <Modal
        visible={pickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setPickerOpen(false)}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close category picker"
          onPress={() => setPickerOpen(false)}
          className="flex-1 justify-end bg-black/60"
        >
          <Pressable
            accessibilityRole="none"
            onPress={() => {}}
            className="rounded-t-2xl border-t border-border bg-card p-4"
          >
            <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              What is this about?
            </Text>

            {contactCategories.map((entry) => {
              const selected = entry.value === category;
              return (
                <Pressable
                  key={entry.value}
                  testID={`contact-form-category-option-${entry.value}`}
                  accessibilityRole="radio"
                  accessibilityLabel={entry.label}
                  accessibilityState={{ selected }}
                  onPress={() => {
                    setCategory(entry.value);
                    setPickerOpen(false);
                  }}
                  className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 active:bg-secondary"
                >
                  <Text className="text-sm text-foreground">{entry.label}</Text>
                  <Text
                    className={`text-sm ${
                      selected ? "text-primary" : "text-muted-foreground"
                    }`}
                  >
                    {selected ? "●" : "○"}
                  </Text>
                </Pressable>
              );
            })}

            <Pressable
              testID="contact-form-category-close"
              accessibilityRole="button"
              accessibilityLabel="Close category picker"
              onPress={() => setPickerOpen(false)}
              className="mt-3 min-h-[44px] items-center justify-center rounded border border-border active:bg-secondary"
            >
              <Text className="text-[13px] font-medium text-foreground">
                Cancel
              </Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

export default ContactForm;
