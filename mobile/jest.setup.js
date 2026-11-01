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

// ``expo-notifications`` warns loudly when it is loaded outside a
// development build, and its auto-registration reaches for a native module
// the test environment does not have. Neither is useful in a unit test, so
// the package is replaced with an inert one. The tests that care about
// push replace the wrapper above it instead.
jest.mock("expo-notifications", () => ({
  getPermissionsAsync: async () => ({ status: "undetermined" }),
  requestPermissionsAsync: async () => ({ status: "undetermined" }),
  getExpoPushTokenAsync: async () => ({ type: "expo", data: "stub-token" }),
  setNotificationHandler: () => {},
  addNotificationResponseReceivedListener: () => ({ remove: () => {} }),
  getLastNotificationResponseAsync: async () => null,
  AndroidImportance: { DEFAULT: 3 },
}));

// React Native provides a global ``WebSocket``. Node does too, and unlike
// React Native's it will happily open a real connection -- which in a unit
// test means a socket to a backend that is not there, and an event loop that
// never closes. The default here is inert; a test that exercises the stream
// installs its own.
class StubWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  readyState = StubWebSocket.CONNECTING;
  url: string;

  constructor(url: string) {
    this.url = url;
  }

  send() {}

  close() {
    this.readyState = StubWebSocket.CLOSED;
  }

  addEventListener() {}
  removeEventListener() {}
}

global.WebSocket = StubWebSocket;

// React Native Reanimated depends on `react-native-worklets` for its
// runtime; both expose native modules that the jest-expo preset does not
// provide. We replace each with a no-op shim that matches the surface the
// skeleton, shimmer and ingest-flow components use: ``useSharedValue``,
// ``useAnimatedStyle``, ``useAnimatedProps``, ``withRepeat``,
// ``withTiming``, ``withSequence``, ``withDelay``, ``cancelAnimation`` and
// ``Easing``.
// Tests that need the actual animation engine (none today) can override
// these mocks locally.
//
// The animation builders resolve to their *target value* rather than to an
// animation object. The real ones return an object the runtime interprets
// on the UI thread; in a test there is no UI thread, so the value itself is
// what an effect can observe, and it keeps derived arithmetic (``1 -
// progress``) from producing ``NaN``.
//
// ``jest.mock`` factories are hoisted, so any value referenced inside
// must be prefixed with ``mock`` (jest's allow-list) or declared inline.
jest.mock("react-native-reanimated", () => {
  const mockNoop = () => {};
  const mockId = (v) => v;

  /**
   * Wrap a component so the ``animatedProps`` prop is consumed rather than
   * forwarded.
   *
   * The real implementation reads ``animatedProps`` off the element and
   * drives the native props itself. Passing it on would hand react-native-svg
   * a prop it does not know.
   */
  const mockCreateAnimatedComponent = (Component) => {
    const ReactLocal = require("react");
    const Wrapped = (props) => {
      const { animatedProps, ...rest } = props || {};
      void animatedProps;
      return ReactLocal.createElement(Component, rest);
    };
    Wrapped.displayName = `AnimatedComponent(${
      Component.displayName || Component.name || "Component"
    })`;
    return Wrapped;
  };

  return {
    __esModule: true,
    default: {
      View: require("react-native").View,
      Text: require("react-native").Text,
      Image: require("react-native").Image,
      ScrollView: require("react-native").ScrollView,
      createAnimatedComponent: mockCreateAnimatedComponent,
    },
    // A stable object per component instance, so an effect keyed on the
    // shared value does not re-run on every render.
    useSharedValue: (init) => {
      const ReactLocal = require("react");
      return ReactLocal.useRef({ value: init }).current;
    },
    useAnimatedStyle: (factory) => factory(),
    useAnimatedProps: () => ({}),
    useAnimatedReaction: mockNoop,
    useDerivedValue: (factory) => ({ value: factory() }),
    useAnimatedRef: () => ({ current: null }),
    useAnimatedScrollHandler: mockNoop,
    useAnimatedSensor: () => ({ sensor: { value: {} } }),
    useReducedMotion: () => false,
    withRepeat: (animation) => animation,
    withTiming: (toValue) => toValue,
    withSpring: (toValue) => toValue,
    withDelay: (_delay, animation) => animation,
    withSequence: (...animations) => animations[animations.length - 1],
    cancelAnimation: mockNoop,
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
