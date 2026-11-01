/**
 * The on-screen keyboard's height, in points.
 *
 * `KeyboardAvoidingView` is not reliable on Android with edge-to-edge
 * enabled (the default from SDK 54 on): the window no longer resizes for
 * the keyboard, and the view's own `height` behaviour does not account for
 * it on every navigator, so a composer pinned to the bottom of a screen
 * ends up underneath the keyboard. Reading the keyboard event directly and
 * adding that much padding is deterministic on both platforms.
 *
 * iOS reports `keyboardWillShow`/`WillHide`, which fire before the
 * animation starts and so can be animated alongside it; Android only has
 * `DidShow`/`DidHide`.
 *
 * @module useKeyboardHeight
 */

import { useEffect, useState } from "react";
import { Keyboard, Platform } from "react-native";

/**
 * Subscribe to the keyboard's height.
 *
 * @returns The keyboard height in points, or 0 when it is closed.
 */
export function useKeyboardHeight(): number {
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const showEvent =
      Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent =
      Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";

    const showSubscription = Keyboard.addListener(showEvent, (event) => {
      setHeight(event.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener(hideEvent, () => {
      setHeight(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  return height;
}

export default useKeyboardHeight;
