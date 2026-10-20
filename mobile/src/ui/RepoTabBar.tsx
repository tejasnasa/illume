/**
 * The repository shell's section tabs.
 *
 * @module RepoTabBar
 *
 * A custom tab bar for the repository shell, replacing the navigator's
 * built-in one.
 *
 * The built-in bar is a *bottom* bar: it wants an icon above every label
 * and reserves a slot for one whether or not an icon is supplied -- a
 * missing icon renders a placeholder glyph, which is not something to
 * ship. The web navbar is the opposite: a row of text links with the
 * active one in the foreground colour. A custom bar is the only way to
 * get that shape, and it also means the bar's height and its safe-area
 * handling are ours rather than the navigator's.
 *
 * The labels are the web client's, unchanged: Home, Glossary, Explorer,
 * Graph.
 */

import { Pressable, Text, View } from "react-native";
import type { BottomTabBarProps } from "expo-router/js-tabs";

/** Props for the {@link RepoTabBar} component. */
export interface RepoTabBarProps extends BottomTabBarProps {
  /**
   * Whether the section tabs are available.
   *
   * A repository that has not been indexed has no glossary, no explorer
   * and no graph, so those tabs are left out of the bar entirely. On the
   * web the links stay visible and greyed out; on a phone three
   * permanently dead tabs crowd out the one that works.
   */
  sectionsAvailable?: boolean;
}

/**
 * The route that is always present, whatever the repository's status.
 */
const OVERVIEW_ROUTE = "index";

/**
 * Render the repository's section tabs.
 *
 * @param props - The navigator's tab bar props, plus whether the sections
 *   are available.
 * @returns The rendered tab bar.
 */
export function RepoTabBar({
  state,
  descriptors,
  navigation,
  sectionsAvailable = true,
}: RepoTabBarProps) {
  const routes = state.routes.filter(
    (route) => sectionsAvailable || route.name === OVERVIEW_ROUTE,
  );

  return (
    <View
      accessibilityRole="tablist"
      className="flex-row border-b border-border bg-background"
    >
      {routes.map((route) => {
        const { options } = descriptors[route.key];
        const focused = state.routes[state.index]?.key === route.key;
        const label =
          typeof options.tabBarLabel === "string"
            ? options.tabBarLabel
            : (options.title ?? route.name);

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

        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={label}
            testID={`repo-tab-${route.name}`}
            onPress={onPress}
            className="flex-1 items-center justify-center px-2 py-3"
          >
            <Text
              className={
                focused
                  ? "text-[13px] font-semibold text-foreground"
                  : "text-[13px] text-muted-foreground"
              }
              numberOfLines={1}
            >
              {label}
            </Text>
            {focused ? (
              <View className="mt-1 h-0.5 w-5 rounded-full bg-foreground" />
            ) : (
              <View className="mt-1 h-0.5 w-5" />
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

export default RepoTabBar;
