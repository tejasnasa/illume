// Mock NativeWind at the test boundary so className-prop components render
// without the runtime CSS interop being involved.
jest.mock("nativewind", () => ({
  styled: (Component) => Component,
  useColorScheme: () => "dark",
}));
