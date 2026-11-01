/**
 * The glossary search field.
 *
 * @module GlossarySearch
 *
 * Port of the search box in ``client/src/components/GlossarySearch.tsx``.
 *
 * The web version is an ``<input>`` with a magnifying glass on the left and
 * a cross on the right; here the field is a ``TextInput`` with the same two
 * affordances drawn as glyphs, because the app carries no icon library.
 * The styling is the app's own field styling -- the one the repository
 * picker uses -- so the two search boxes in the app look like each other.
 *
 * The box is controlled: the text belongs to the search hook, which owns the
 * debounce that decides when the text becomes a request.
 */

import { Pressable, Text, TextInput, View } from "react-native";

import { colors } from "@/theme/tokens";

/** Props for the {@link GlossarySearch} component. */
export interface GlossarySearchProps {
  /** The text currently in the field. */
  value: string;
  /** Called with the new text on every keystroke. */
  onChangeText: (value: string) => void;
  /** Called when the reader taps the cross. */
  onClear: () => void;
  /** The text shown while the field is empty. */
  placeholder?: string;
  /** Test hook. */
  testID?: string;
}

/**
 * Draw the glossary search field.
 *
 * @param props - The field's text, its handlers and its placeholder.
 * @returns The rendered field.
 */
export function GlossarySearch({
  value,
  onChangeText,
  onClear,
  placeholder = "Search definitions...",
  testID = "glossary-search",
}: GlossarySearchProps) {
  return (
    <View className="min-h-[44px] flex-row items-center rounded border border-border bg-secondary/10 px-3">
      <Text className="mr-2 text-sm text-muted-foreground">🔍</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.mutedForeground}
        className="flex-1 py-2.5 text-sm text-foreground"
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        accessibilityRole="search"
        accessibilityLabel="Search glossary definitions"
      />
      {value.length > 0 ? (
        <Pressable
          testID="glossary-search-clear"
          accessibilityRole="button"
          accessibilityLabel="Clear search"
          onPress={onClear}
          hitSlop={8}
          className="rounded p-1 active:bg-secondary"
        >
          <Text className="text-sm text-muted-foreground">✕</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default GlossarySearch;
