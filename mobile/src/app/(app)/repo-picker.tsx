/**
 * Full-screen repository picker.
 *
 * @module RepoPickerRoute
 *
 * The web app opens the repository picker inside a centred ``<Modal>``. On
 * a phone that wastes the screen and fights the soft keyboard, so the
 * picker is a **modal route** instead: a full-height sheet that slides up
 * over the dashboard and can be dismissed with the hardware back button.
 *
 * The route is registered in ``(app)/_layout.tsx`` with
 * ``presentation: "modal"`` so the platform supplies the sheet chrome.
 *
 * **Navigation on success.** The picker is a route, so a plain ``push``
 * of the new repository's page would leave the picker underneath it and
 * the back button would return to the picker rather than to the
 * dashboard. ``replace`` swaps the picker out for the repository page
 * instead, which is what the user expects: the dashboard is still behind
 * it, and back goes there.
 */

import { router } from "expo-router";

import { RepoPickerModal } from "@/components/RepoPickerModal";

export default function RepoPickerRoute() {
  return (
    <RepoPickerModal
      onClose={(repoNum) => {
        if (repoNum === null) {
          router.back();
          return;
        }
        router.replace(`/(app)/repo/${repoNum}`);
      }}
    />
  );
}
