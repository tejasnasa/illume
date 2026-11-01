# End-to-end flows

Maestro flows that drive the built app on a real device.

```bash
maestro test e2e/
```

The app has to be installed on the device first, and the backend has to be
reachable from it:

```bash
npx eas build --profile preview --platform android   # an APK you can install
```

## The account

Sign-in is a GitHub OAuth round trip through a system browser, which Maestro
cannot drive. **Sign in by hand once per device**, then run the flows —
Maestro's `launchApp` does not clear the app's state, so the session
survives between runs.

Use a seeded account rather than a real one. The flows read and write
repositories, and a real account is where mistakes land.

## The flows

| Flow            | What it covers                                                   |
| --------------- | ---------------------------------------------------------------- |
| `onboarding.yaml` | The first-run carousel. **Clears the app's state.**              |
| `dashboard.yaml`  | The signed-in home screen.                                       |
| `repository.yaml` | The repository shell and its section tabs.                       |
| `chat.yaml`       | The chat screen, and a question answered with citations.        |

`onboarding.yaml` clears the app's state, so it signs the device out. Run
it first, sign in again by hand, and run the rest.

## The repository number

The flows deep-link into repository `1`. That is the user-scoped number of
the first repository the seeded account owns, which is not the same as the
repository's UUID — the deep link uses the number because that is what the
app's routes are keyed on. Change it in the flow files if the seeded
account's first repository is not number 1.
