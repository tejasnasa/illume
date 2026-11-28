import { fireEvent, render, screen } from "@testing-library/react-native";

import { FONT_FILES } from "@/lib/fonts";
import { Button } from "@/ui/Button";
import { Logo, Wordmark } from "@/ui/Logo";
import { Eyebrow, Panel } from "@/ui/Panel";
import { Screen } from "@/ui/Screen";
import { Starfield } from "@/ui/Starfield";
import { Text } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

describe("design system primitives", () => {
  it("loads Geist Sans in four weights and the pixel face", () => {
    expect(Object.keys(FONT_FILES).sort()).toEqual([
      "Geist-Bold",
      "Geist-Medium",
      "Geist-Regular",
      "Geist-SemiBold",
      "GeistPixel-Square",
    ]);
  });

  it("renders the logo and the wordmark", async () => {
    await render(<Logo size={40} />);
    expect(screen.getByTestId("logo", { includeHiddenElements: true })).toBeTruthy();
    await render(<Wordmark />);
    expect(screen.getByText("illume")).toBeTruthy();
  });

  it("renders the starfield without taking touches", async () => {
    await render(<Starfield />);
    expect(screen.getByTestId("starfield", { includeHiddenElements: true }).props.pointerEvents).toBe("none");
  });

  it("wraps screen content", async () => {
    await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 360, height: 800 },
          insets: { top: 24, left: 0, right: 0, bottom: 0 },
        }}
      >
        <Screen>
          <Text>inside</Text>
        </Screen>
      </SafeAreaProvider>,
    );
    expect(screen.getByText("inside")).toBeTruthy();
    expect(screen.getByTestId("starfield", { includeHiddenElements: true })).toBeTruthy();
  });

  it("renders a panel and an eyebrow label", async () => {
    await render(
      <Panel testID="panel">
        <Eyebrow>Architecture</Eyebrow>
      </Panel>,
    );
    expect(screen.getByText("Architecture")).toBeTruthy();
    expect(screen.getByTestId("panel")).toBeTruthy();
  });

  it("fires a button press and ignores it while loading or disabled", async () => {
    const onPress = jest.fn();
    const { rerender } = await render(
      <Button onPress={onPress} testID="b">
        Go
      </Button>,
    );
    await fireEvent.press(screen.getByTestId("b"));
    expect(onPress).toHaveBeenCalledTimes(1);

    await rerender(
      <Button onPress={onPress} testID="b" loading>
        Go
      </Button>,
    );
    await fireEvent.press(screen.getByTestId("b"));
    await rerender(
      <Button onPress={onPress} testID="b" disabled>
        Go
      </Button>,
    );
    await fireEvent.press(screen.getByTestId("b"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});
