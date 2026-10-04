/**
 * Signs in once, proves the session cookie can actually reach both origins, and checks the
 * preconditions every other project depends on.
 *
 * **Through the API, not the login page**, and that is not a shortcut. `LoginForm` is a
 * single "Continue with GitHub" button with no credential fields, and there is no `/signup`
 * route either, so an E2E run cannot sign in the way a user would -- because no such user
 * can. Driving the real GitHub round trip would put a third party in the critical path of a
 * nightly job.
 *
 * The smoke account does have a password and `POST /api/v1/auth/login` accepts it, so the
 * cookie written here is a real session cookie from the real endpoint -- the same one the
 * browser holds after an OAuth round trip. What is skipped is the GitHub redirect.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test as setup } from "@playwright/test";

import {
  SMOKE_API_URL,
  SMOKE_BASE_URL,
  SMOKE_COOKIE_DOMAIN,
  SMOKE_EMAIL,
  SMOKE_PASSWORD,
  SMOKE_REPO_NAME,
} from "./env";
import { ARTIFACT_DIR, SMOKE_INFO, STORAGE_STATE } from "./fixtures";

/** Pulls the session cookie out of the response without splitting on commas. */
function sessionCookie(headers: { name: string; value: string }[]): string {
  const found = headers
    .filter((header) => header.name.toLowerCase() === "set-cookie")
    .map((header) => header.value)
    .find((value) => value.startsWith("access_token="));

  if (!found) {
    throw new Error(
      "the login response set no access_token cookie. A 200 without a session cookie means " +
        "the endpoint changed shape, not that the credentials were wrong.",
    );
  }
  return found;
}

setup("authenticate and verify the production target", async ({ request }) => {
  const webHost = new URL(SMOKE_BASE_URL).host;
  const apiHost = new URL(SMOKE_API_URL).host;

  // An absolute URL on purpose: the `request` fixture's baseURL is the *web* origin, which
  // serves no API routes and would answer an HTML 404 rather than a session. Note also that
  // this client is not CORS-constrained, so a 200 here says nothing about the browser --
  // `public.spec.ts` makes the same call from inside a page for that reason.
  const login = await request.post(`${SMOKE_API_URL}/api/v1/auth/login`, {
    data: { email: SMOKE_EMAIL, password: SMOKE_PASSWORD },
  });
  expect(
    login.status(),
    `login failed: ${login.status()} ${await login.text()}. A 500 here usually means the ` +
      "account has no password -- it was created through GitHub rather than the register API.",
  ).toBe(200);

  const cookie = sessionCookie(await login.headersArray());
  // Attributes only, never the token. This string goes into assertion messages, and a
  // failing run's output is uploaded as a report artifact -- the same reason traces are off.
  const attributeList = cookie.includes(";") ? cookie.slice(cookie.indexOf(";")) : "";
  const attributes = attributeList.toLowerCase();

  // The assertion this suite exists for. The cookie is set with `domain=settings.DOMAIN`,
  // and both origins have to see it: the API to authenticate the call, the web origin
  // because the Next proxy gates /dashboard and /repo on it being present there. When
  // DOMAIN is host-only for the API, the proxy never finds it and every protected route
  // redirects to /login forever -- which without this check surfaces as a navigation
  // timeout pointing at nothing.
  const domain = /;\s*domain=([^;]+)/.exec(attributes)?.[1]?.trim().replace(/^\./, "");
  expect(
    domain,
    `the session cookie carries no Domain attribute (${attributeList}). It is host-only for ` +
      `${apiHost}, so ${webHost} will never see it. Check DOMAIN on the droplet -- it must ` +
      `be .${SMOKE_COOKIE_DOMAIN} for the two hosts to share the session.`,
  ).toBe(SMOKE_COOKIE_DOMAIN);

  expect(attributes, `the session cookie is not Secure: ${attributeList}`).toContain("secure");
  expect(attributes, `the session cookie is not HttpOnly: ${attributeList}`).toContain("httponly");
  expect(attributes, `the session cookie is not SameSite=Lax: ${attributeList}`).toContain(
    "samesite=lax",
  );

  mkdirSync(ARTIFACT_DIR, { recursive: true });
  await request.storageState({ path: STORAGE_STATE });

  // Checked twice on purpose: the raw header proves what the server sent, and the stored
  // state proves what the browser will actually carry. A normalisation difference between
  // them is exactly the kind of thing that would otherwise only show up as a mystery
  // redirect much later.
  const state = JSON.parse(readFileSync(STORAGE_STATE, "utf-8")) as {
    cookies: { name: string; domain: string; secure: boolean }[];
  };
  const stored = state.cookies.find((entry) => entry.name === "access_token");
  expect(stored, "the stored session state has no access_token cookie").toBeTruthy();
  expect(stored!.domain.replace(/^\./, "")).toBe(SMOKE_COOKIE_DOMAIN);
  expect(stored!.secure, "the stored session cookie is not Secure").toBe(true);

  // Precondition: the repository the specs browse exists, belongs to this account, and is
  // finished. A repository still ingesting makes the chat endpoint 400, which would look
  // like a chat bug rather than an unfinished seed.
  const list = await request.get(`${SMOKE_API_URL}/api/v1/repository`);
  expect(list.status(), `listing repositories failed: ${list.status()}`).toBe(200);
  const repos = (await list.json()) as {
    id: string;
    name: string;
    repo_number: number;
    status: string;
  }[];
  const repo = repos.find((candidate) => candidate.name === SMOKE_REPO_NAME);
  expect(
    repo,
    `the smoke account owns no repository named ${JSON.stringify(SMOKE_REPO_NAME)}; it has: ` +
      `${repos.map((candidate) => candidate.name).join(", ") || "none"}. Ingest one, then set ` +
      "SMOKE_REPO_NAME to it.",
  ).toBeTruthy();
  expect(
    repo!.status,
    `${SMOKE_REPO_NAME} is ${repo!.status}; the specs need a repository that finished ingesting`,
  ).toBe("ready");

  // Precondition: chat runs on the account's own key. Without it the free path takes over,
  // and the ten-message lifetime allowance would be gone inside a week of nightly runs.
  const me = await request.get(`${SMOKE_API_URL}/api/v1/auth/me`);
  expect(me.status(), `reading the account failed: ${me.status()}`).toBe(200);
  const account = (await me.json()) as {
    has_ai_key: boolean;
    free_chat_messages_used: number;
  };
  expect(
    account.has_ai_key,
    "the smoke account has no AI key, so chat would fall back to the server key and drain " +
      "the free tier. Save a key on the account before running this suite.",
  ).toBe(true);

  // Start from a known state. This is also what makes the lack of a janitor safe: if a run
  // is killed before its teardown, the next run clears the history before writing to it, so
  // accumulation is bounded to at most one run's turns.
  const cleared = await request.delete(`${SMOKE_API_URL}/api/v1/repository/${repo!.id}/chat`);
  expect(cleared.status(), `clearing chat history failed: ${cleared.status()}`).toBe(204);

  writeFileSync(
    SMOKE_INFO,
    JSON.stringify(
      {
        repo: { id: repo!.id, name: repo!.name, repoNumber: repo!.repo_number },
        freeChatMessagesUsed: account.free_chat_messages_used,
      },
      null,
      2,
    ),
  );
});
