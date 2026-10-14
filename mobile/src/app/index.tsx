import { Redirect } from "expo-router";

/**
 * Entry route. The authenticated-route guard ships in a later milestone;
 * today we simply send the user to the onboarding carousel.
 */
export default function Index() {
  return <Redirect href="/onboarding" />;
}
