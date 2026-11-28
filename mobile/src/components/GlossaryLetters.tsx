/**
 * The glossary's A to Z rail: one small card per initial, filtering the list.
 *
 * @module GlossaryLetters
 *
 * Port of ``client/src/components/ui/GlossaryLetters.tsx``. Initials with no
 * terms stay visible but inert, so the rail keeps its shape whatever the
 * glossary holds. `#` collects names that start with anything but a letter.
 */

import { Pressable, Text, View } from "react-native";

/** Every initial the rail offers, in order. */
export const GLOSSARY_INITIALS: readonly string[] = [
  ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ",
  "#",
];

/**
 * Reads a value as one of the rail's initials.
 *
 * @param value - The raw value, if any.
 * @returns The initial in upper case, or null when it is missing or not one.
 */
export function parseInitial(value: string | null | undefined): string | null {
  const upper = (value ?? "").toUpperCase();
  return GLOSSARY_INITIALS.includes(upper) ? upper : null;
}

const CELL = "h-9 min-w-9 items-center justify-center rounded-sm border px-2";

/**
 * Renders the rail.
 *
 * @param props - The active initial, the initials that have terms and the
 *   handler that picks one (or null for all terms).
 * @returns The rail.
 */
export function GlossaryLetters({
  active,
  present,
  onSelect,
}: {
  active: string | null;
  present: readonly string[];
  onSelect: (letter: string | null) => void;
}) {
  const available = new Set(present);
  const on = "border-accent bg-accent/15";
  const off = "border-border bg-card";

  return (
    <View
      testID="glossary-letters"
      accessibilityLabel="Filter by letter"
      className="flex-row flex-wrap gap-1"
    >
      <Pressable
        testID="glossary-letter-all"
        accessibilityRole="button"
        accessibilityState={{ selected: active === null }}
        onPress={() => onSelect(null)}
        className={`${CELL} ${active === null ? on : off}`}
      >
        <Text
          className={`font-pixel text-xs uppercase ${active === null ? "text-accent" : "text-zinc-300"}`}
        >
          All
        </Text>
      </Pressable>
      {GLOSSARY_INITIALS.map((letter) => {
        const usable = available.has(letter) || letter === active;
        const label = letter === "#" ? "Other" : letter;
        return usable ? (
          <Pressable
            key={letter}
            testID={`glossary-letter-${letter}`}
            accessibilityRole="button"
            accessibilityLabel={label}
            accessibilityState={{ selected: letter === active }}
            onPress={() => onSelect(letter)}
            className={`${CELL} ${letter === active ? on : off}`}
          >
            <Text
              className={`font-pixel text-xs uppercase ${letter === active ? "text-accent" : "text-zinc-300"}`}
            >
              {letter}
            </Text>
          </Pressable>
        ) : (
          <View
            key={letter}
            testID={`glossary-letter-${letter}`}
            accessibilityState={{ disabled: true }}
            accessibilityLabel={`${label}, no terms`}
            className={`${CELL} ${off}`}
          >
            <Text className="font-pixel text-xs uppercase text-zinc-700">{letter}</Text>
          </View>
        );
      })}
    </View>
  );
}
