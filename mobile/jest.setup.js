// Mock NativeWind and its v5 engine at the test boundary so
// ``className``-styled components render without the runtime CSS
// interop being involved. In v5 the styled API lives on ``nativewind``;
// ``react-native-css`` is the engine it delegates to. Neither is used
// by application code directly, but transitive deps may import them.
jest.mock("nativewind", () => ({
  styled: (Component) => Component,
  useColorScheme: () => "dark",
}));

jest.mock("react-native-css", () => ({}));

// React Native Reanimated depends on `react-native-worklets` for its
// runtime; both expose native modules that the jest-expo preset does not
// provide. We replace each with a no-op shim that matches the surface the
// skeleton + shimmer components use: ``useSharedValue``,
// ``useAnimatedStyle``, ``withRepeat``, ``withTiming``, and ``Easing``.
// Tests that need the actual animation engine (none today) can override
// these mocks locally.
//
// ``jest.mock`` factories are hoisted, so any value referenced inside
// must be prefixed with ``mock`` (jest's allow-list) or declared inline.
jest.mock("react-native-reanimated", () => {
  const mockNoop = () => {};
  const mockId = (v) => v;

  return {
    __esModule: true,
    default: {
      View: require("react-native").View,
      Text: require("react-native").Text,
      Image: require("react-native").Image,
      ScrollView: require("react-native").ScrollView,
      createAnimatedComponent: (Component) => Component,
    },
    useSharedValue: (init) => ({ value: init }),
    useAnimatedStyle: (factory) => factory(),
    useAnimatedProps: () => ({}),
    useAnimatedReaction: mockNoop,
    useDerivedValue: (factory) => ({ value: factory() }),
    useAnimatedRef: () => ({ current: null }),
    useAnimatedScrollHandler: mockNoop,
    useAnimatedSensor: () => ({ sensor: { value: {} } }),
    withRepeat: (animation) => animation,
    withTiming: (toValue) => ({ toValue }),
    withSpring: (toValue) => ({ toValue }),
    withDelay: (_delay, animation) => animation,
    withSequence: (...animations) => animations[animations.length - 1],
    Easing: {
      linear: mockId,
      ease: mockId,
      in: mockId,
      out: mockId,
      inOut: mockId,
      bezier: () => mockId,
    },
    runOnJS: (fn) => fn,
    runOnUI: (fn) => fn,
  };
});

jest.mock("react-native-worklets", () => {
  const mockNoop = () => {};
  return {
    __esModule: true,
    isWorkletFunction: () => false,
    runOnJS: (fn) => fn,
    runOnUI: (fn) => fn,
    createWorkletRuntime: mockNoop,
  };
});
