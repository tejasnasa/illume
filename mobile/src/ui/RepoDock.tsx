/**
 * The repository's bottom navigation dock.
 *
 * @module RepoDock
 *
 * A custom tab bar for the repository shell. It is part of the layout --
 * the screens above it end where it begins, so none of them needs bottom
 * padding of its own -- and it sits above the bottom safe-area inset.
 *
 * Five slots in a fixed order: Overview, Graph, Ask, Files, Terms. Ask is
 * the centre slot and is drawn as a raised square button that opens the
 * chat. The active slot is foreground-coloured with a short pink bar on the
 * dock's top edge; the others are dimmed.
 *
 * A repository that has not been indexed has no graph, files, terms or chat,
 * so only Overview is listed for it.
 */

import { useEffect, useState } from "react";
import { Keyboard, Pressable, Text, View } from "react-native";
import type { BottomTabBarProps } from "expo-router/js-tabs";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PIXEL_FONT } from "@/lib/fonts";
import { colors } from "@/theme/tokens";
import { PixelIcon, type PixelIconName } from "@/ui/PixelIcon";

/** Height of the dock above the safe-area inset, in points. */
export const DOCK_HEIGHT = 56;

/** Side of the raised Ask button, in points. */
const ASK_SIZE = 48;

/** How far the Ask button rises above the dock's top edge, in points. */
const ASK_RAISE = 16;

/** One slot of the dock. */
interface DockSlot {
  /** The navigator route the slot opens. */
  route: string;
  /** The label under the icon. */
  label: string;
  /** The icon, or ``null`` for the Ask button which draws a glyph. */
  icon: PixelIconName | null;
}

/** The slots, in the order they are drawn. */
export const DOCK_SLOTS: readonly DockSlot[] = [
  { route: "index", label: "Overview", icon: "overview" },
  { route: "graph", label: "Graph", icon: "graph" },
  { route: "chat", label: "Ask", icon: null },
  { route: "explorer", label: "Files", icon: "files" },
  { route: "glossary", label: "Terms", icon: "terms" },
];

/** The route that is always present, whatever the repository's status. */
const OVERVIEW_ROUTE = "index";

/** Props for the {@link RepoDock} component. */
export interface RepoDockProps extends BottomTabBarProps {
  /**
   * Whether the repository's sections are available.
   *
   * Until the repository has been indexed only Overview is listed.
   */
  sectionsAvailable?: boolean;
}

/**
 * Whether the on-screen keyboard is showing.
 *
 * The dock steps aside for the keyboard so the chat composer keeps the room.
 *
 * @returns ``true`` while the keyboard is visible.
 */
function useKeyboardVisible(): boolean {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", () => setVisible(true));
    const hide = Keyboard.addListener("keyboardDidHide", () => setVisible(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  return visible;
}

/**
 * Render the dock.
 *
 * @param props - The navigator's tab bar props, plus whether the sections
 *   are available.
 * @returns The dock.
 */
export function RepoDock({
  state,
  navigation,
  sectionsAvailable = true,
}: RepoDockProps) {
  const insets = useSafeAreaInsets();
  const keyboardVisible = useKeyboardVisible();
  if (keyboardVisible) return null;

  const focusedKey = state.routes[state.index]?.key;

  const slots = DOCK_SLOTS.flatMap((slot) => {
    if (!sectionsAvailable && slot.route !== OVERVIEW_ROUTE) return [];
    const route = state.routes.find((r) => r.name === slot.route);
    return route ? [{ slot, route }] : [];
  });

  return (
    <View
      accessibilityRole="tablist"
      testID="repo-dock"
      style={{
        height: DOCK_HEIGHT + insets.bottom,
        paddingBottom: insets.bottom,
        backgroundColor: colors.card,
        borderTopWidth: 1,
        borderTopColor: colors.border,
        flexDirection: "row",
      }}
    >
      {slots.map(({ slot, route }) => {
        const focused = route.key === focusedKey;

        const onPress = () => {
          const event = navigation.emit({
            type: "tabPress",
            target: route.key,
            canPreventDefault: true,
          });
          if (!focused && !event.defaultPrevented) {
            navigation.navigate(route.name);
          }
        };

        const isAsk = slot.icon === null;
        const tint = focused ? colors.foreground : colors.subtleForeground;

        return (
          <Pressable
            key={route.key}
            testID={`repo-tab-${route.name}`}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={slot.label}
            onPress={onPress}
            style={{
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
              minHeight: 44,
            }}
          >
            {focused ? (
              <View
                testID={`repo-tab-active-${route.name}`}
                style={{
                  position: "absolute",
                  top: -1,
                  width: 24,
                  height: 3,
                  backgroundColor: colors.accent,
                }}
              />
            ) : null}

            {isAsk ? (
              <View
                style={{
                  position: "absolute",
                  top: -ASK_RAISE,
                  width: ASK_SIZE,
                  height: ASK_SIZE,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: colors.primary,
                  borderWidth: 2,
                  borderColor: focused ? colors.foreground : colors.accent,
                  borderRadius: 6,
                }}
              >
                <Text
                  style={{
                    fontFamily: PIXEL_FONT,
                    fontSize: 14,
                    lineHeight: 16,
                    color: colors.primaryForeground,
                  }}
                >
                  {">_"}
                </Text>
                <Text
                  style={{
                    fontFamily: PIXEL_FONT,
                    fontSize: 9,
                    lineHeight: 11,
                    letterSpacing: 1,
                    color: colors.primaryForeground,
                  }}
                >
                  ASK
                </Text>
              </View>
            ) : (
              <>
                <PixelIcon name={slot.icon!} size={18} color={tint} />
                <Text
                  numberOfLines={1}
                  style={{
                    marginTop: 5,
                    fontFamily: PIXEL_FONT,
                    fontSize: 9,
                    lineHeight: 11,
                    letterSpacing: 1,
                    textTransform: "uppercase",
                    color: tint,
                  }}
                >
                  {slot.label}
                </Text>
              </>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

export default RepoDock;
