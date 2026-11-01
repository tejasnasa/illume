/**
 * The first-run carousel.
 *
 * @module OnboardingCarousel
 *
 * Three screens that say what Illume does, what it produces, and why it
 * never needs more than read access to a repository. This is the mobile
 * answer to the web's scroll-driven landing page, which does not port: the
 * same introduction, in a form a thumb can use.
 *
 * The component owns the paging -- a horizontal :component:`FlatList` with
 * ``pagingEnabled`` -- plus the dots and the two actions. It deliberately
 * owns no navigation: the route that hosts it decides where the reader goes
 * once they are done.
 *
 * The copy lives in {@link ONBOARDING_PAGES} so the three screens can be
 * read, and changed, in one place.
 */

import { useCallback, useRef, useState } from "react";
import {
  FlatList,
  Pressable,
  Text,
  View,
  useWindowDimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/theme/tokens";

/** One screen of the carousel. */
export interface OnboardingPage {
  /** Stable identifier, used as the list key. */
  id: string;
  /** Glyph shown above the headline. */
  glyph: string;
  /** The headline. */
  title: string;
  /** The paragraph under the headline. */
  body: string;
  /** Optional bullet list under the paragraph. */
  bullets?: string[];
}

/** The three screens, in order. */
export const ONBOARDING_PAGES: OnboardingPage[] = [
  {
    id: "reads",
    glyph: "🔎",
    title: "It reads your repository",
    body: "Point Illume at a GitHub repository and it does what a new hire would: it reads every file, follows every import, and works out which parts of the code depend on which.",
  },
  {
    id: "produces",
    glyph: "🗺️",
    title: "It hands you a map",
    body: "One pass over the code, four things to work with:",
    bullets: [
      "A glossary that explains the code in plain English.",
      "A reading order that says where to start.",
      "A dependency graph you can walk around.",
      "A chat that answers questions about the code.",
    ],
  },
  {
    id: "read-only",
    glyph: "🔒",
    title: "It only ever reads",
    body: "Illume clones your repository to analyse it. That is the whole of it.",
    bullets: [
      "It never writes to your code and never opens a pull request.",
      "It never asks for a permission wider than reading your repositories.",
    ],
  },
];

/** Props for the {@link OnboardingCarousel} component. */
export interface OnboardingCarouselProps {
  /** Called when the reader taps "Skip" on the first screen. */
  onSkip?: () => void;
  /** Called when the reader taps "Get started" on the last screen. */
  onComplete?: () => void;
}

/**
 * The three-screen introduction.
 *
 * @param props - The two actions the carousel reports back through.
 * @returns The carousel.
 */
export function OnboardingCarousel({
  onSkip,
  onComplete,
}: OnboardingCarouselProps) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const listRef = useRef<FlatList<OnboardingPage>>(null);
  const [index, setIndex] = useState(0);

  const lastIndex = ONBOARDING_PAGES.length - 1;
  const isFirst = index === 0;
  const isLast = index === lastIndex;

  /**
   * Jump to a screen and move the list with it.
   *
   * The dots are the only way to move backwards without swiping, so they
   * have to take the list with them -- otherwise the dots and the visible
   * screen would disagree.
   *
   * @param next - The screen to show; clamped to the available range.
   */
  const goTo = useCallback(
    (next: number) => {
      const clamped = Math.max(0, Math.min(next, lastIndex));
      setIndex(clamped);
      listRef.current?.scrollToOffset({
        offset: clamped * width,
        animated: true,
      });
    },
    [lastIndex, width],
  );

  /**
   * Follow the reader's swipes.
   *
   * The offset is rounded to the nearest page, so the dots settle on the
   * screen the reader is actually looking at rather than the one the finger
   * is passing over.
   *
   * @param event - The scroll event.
   */
  const handleScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, layoutMeasurement } = event.nativeEvent;
      const pageWidth = layoutMeasurement.width || width;
      if (!pageWidth) return;
      const next = Math.round(contentOffset.x / pageWidth);
      setIndex((current) => (current === next ? current : next));
    },
    [width],
  );

  /**
   * The fixed size of one screen.
   *
   * @param _data - The list data; unused.
   * @param itemIndex - The screen being measured.
   * @returns The offset and length of that screen.
   */
  const getItemLayout = useCallback(
    (
      _data: ArrayLike<OnboardingPage> | null | undefined,
      itemIndex: number,
    ) => ({
      length: width,
      offset: width * itemIndex,
      index: itemIndex,
    }),
    [width],
  );

  return (
    // A plain ``View`` padded by the insets: ``className`` does not reach
    // the safe-area component's native view, so its ``flex-1`` was ignored.
    <View
      className="flex-1 bg-background"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      <View className="flex-row items-center justify-between px-5 py-2">
        <Text className="text-[11px] font-bold uppercase tracking-[2px] text-muted-foreground">
          Illume
        </Text>
        {isFirst ? (
          <Pressable
            testID="onboarding-skip"
            accessibilityRole="button"
            accessibilityLabel="Skip the introduction"
            accessibilityState={{ disabled: !onSkip }}
            onPress={onSkip}
            hitSlop={8}
            className="min-h-[44px] justify-center rounded px-2 active:bg-secondary"
          >
            <Text className="text-sm font-semibold text-muted-foreground">
              Skip
            </Text>
          </Pressable>
        ) : (
          // Keeps the wordmark where it is instead of letting it drift left
          // once the button disappears.
          <View className="min-h-[44px] w-12" />
        )}
      </View>

      <FlatList
        ref={listRef}
        testID="onboarding-pages"
        className="flex-1"
        data={ONBOARDING_PAGES}
        keyExtractor={(page) => page.id}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        initialNumToRender={ONBOARDING_PAGES.length}
        getItemLayout={getItemLayout}
        onScroll={handleScroll}
        scrollEventThrottle={16}
        renderItem={({ item, index: pageIndex }) => (
          <View
            testID={`onboarding-page-${pageIndex}`}
            style={{ width }}
            className="items-center justify-center px-8"
          >
            <Text className="mb-6 text-center text-[52px]">{item.glyph}</Text>
            <Text
              accessibilityRole="header"
              className="text-center text-[26px] font-bold text-foreground"
            >
              {item.title}
            </Text>
            <Text className="mt-3 text-center text-[15px] leading-6 text-muted-foreground">
              {item.body}
            </Text>
            {item.bullets ? (
              <View className="mt-6 w-full max-w-[320px] gap-3">
                {item.bullets.map((bullet) => (
                  <View
                    key={bullet}
                    className="flex-row items-start justify-center gap-2"
                  >
                    <Text className="text-[15px] leading-6 text-primary">
                      •
                    </Text>
                    <Text className="flex-1 text-[14px] leading-6 text-muted-foreground">
                      {bullet}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        )}
      />

      <View className="px-6 pb-8 pt-4">
        <View className="mb-4 flex-row items-center justify-center">
          {ONBOARDING_PAGES.map((page, dotIndex) => {
            const isActive = dotIndex === index;
            return (
              <Pressable
                key={page.id}
                testID={`onboarding-dot-${dotIndex}`}
                accessibilityRole="button"
                accessibilityLabel={`Go to screen ${dotIndex + 1} of ${ONBOARDING_PAGES.length}`}
                accessibilityState={{ selected: isActive }}
                onPress={() => goTo(dotIndex)}
                hitSlop={8}
                className="min-h-[44px] min-w-[28px] items-center justify-center"
              >
                <View
                  className="h-2 w-2 rounded-full"
                  style={{
                    backgroundColor: isActive
                      ? colors.primary
                      : colors.mutedForeground,
                    opacity: isActive ? 1 : 0.4,
                  }}
                />
              </Pressable>
            );
          })}
        </View>

        {/*
          The button area keeps its height on every screen, so the dots do
          not jump when the last screen swaps "Skip" for "Get started".
        */}
        <View className="min-h-[48px] justify-center">
          {isLast ? (
            <Pressable
              testID="onboarding-get-started"
              accessibilityRole="button"
              accessibilityLabel="Get started"
              accessibilityState={{ disabled: !onComplete }}
              onPress={onComplete}
              className="min-h-[44px] w-full items-center justify-center rounded bg-primary px-4 py-3 active:bg-secondary"
            >
              <Text className="text-sm font-semibold text-primary-foreground">
                Get started
              </Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </View>
  );
}

export default OnboardingCarousel;
