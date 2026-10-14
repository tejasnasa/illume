/**
 * Smoke test that NativeWind is wired up: a className-styled Text
 * renders without throwing. The end-to-end visual check (does the
 * className compile to the right color?) lives on-device.
 */
import React from "react";
import { Text } from "react-native";
import { render } from "@testing-library/react-native";

describe("NativeWind", () => {
  it("accepts className on RN primitives", async () => {
    expect(() =>
      render(<Text className="text-foreground">hi</Text>),
    ).not.toThrow();
  });
});
