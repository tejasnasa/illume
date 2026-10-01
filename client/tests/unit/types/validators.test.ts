import { describe, expect, it } from "vitest";

import {
  contactCategories,
  contactSchema,
  loginSchema,
  repoCreateSchema,
  signupSchema,
} from "@/types/validators";

/**
 * These schemas are the client's only gate before a request leaves the browser. Each one
 * is checked in both directions -- a valid payload passes and each invalid variant fails
 * with the message the form renders -- because a schema that rejects everything is as
 * broken as one that accepts everything, and only the second is obvious.
 */

/** The first error message a schema reports for `value`. */
function firstError(result: {
  success: boolean;
  error?: { issues: { message: string }[] };
}): string | undefined {
  return result.error?.issues[0]?.message;
}

describe("signupSchema", () => {
  const valid = {
    name: "Ada Lovelace",
    email: "ada@example.com",
    password: "correct-horse-1",
  };

  it("accepts a valid payload", () => {
    expect(signupSchema.safeParse(valid).success).toBe(true);
  });

  it("accepts a name of exactly two characters", () => {
    // The bound is `min(2, ...)`, so the shortest legal name sits on the boundary.
    expect(signupSchema.safeParse({ ...valid, name: "Al" }).success).toBe(true);
  });

  it("rejects a one-character name", () => {
    const result = signupSchema.safeParse({ ...valid, name: "A" });

    expect(result.success).toBe(false);
    expect(firstError(result)).toMatch(/at least 2 characters/i);
  });

  it("rejects a malformed email", () => {
    const result = signupSchema.safeParse({ ...valid, email: "not-an-email" });

    expect(result.success).toBe(false);
    expect(firstError(result)).toMatch(/valid email/i);
  });

  it("trims surrounding whitespace from an email", () => {
    // `.trim()` runs before the format check, so a pasted address with a surrounding
    // space is normalised rather than rejected -- and the parsed value is the trimmed
    // one, which is what actually gets submitted.
    const result = signupSchema.safeParse({ ...valid, email: "  ada@example.com  " });

    expect(result.success).toBe(true);
    expect(result.data?.email).toBe("ada@example.com");
  });

  it("accepts a password of exactly eight characters", () => {
    // Eight characters *and* the three required classes: a letter, a digit, a symbol.
    expect(signupSchema.safeParse({ ...valid, password: "abcdef1!" }).success).toBe(true);
  });

  it("strips surrounding whitespace from a password", () => {
    // Trimming changes the value that gets submitted, so a password may not begin or end
    // with a space -- and because it now runs *before* the length and character-class
    // checks, it can no longer be used to pad a short password past `min(8)` either.
    const result = signupSchema.safeParse({ ...valid, password: "  abcdef1!  " });

    expect(result.success).toBe(true);
    expect(result.data?.password).toBe("abcdef1!");
  });

  it.each([
    ["too short", "abc1!", /at least 8 characters/i],
    ["letters only", "abcdefghij", /at least one number/i],
    ["digits only", "1234567890", /at least one letter/i],
    ["letters and digits only", "abcdefgh1234", /special character/i],
  ])("rejects a password that is %s", (_label, password, expected) => {
    const result = signupSchema.safeParse({ ...valid, password });

    expect(result.success).toBe(false);
    expect(firstError(result)).toMatch(expected);
  });

  it("reports the length failure before the character-class ones", () => {
    // "abc" is short *and* missing a digit and a symbol. The length message is the one
    // shown, because it is the only actionable thing at that point.
    const result = signupSchema.safeParse({ ...valid, password: "abc" });

    expect(firstError(result)).toMatch(/at least 8 characters/i);
  });

  it("rejects a missing field", () => {
    const result = signupSchema.safeParse({ email: valid.email, password: valid.password });

    expect(result.success).toBe(false);
  });
});

describe("loginSchema", () => {
  const valid = { email: "ada@example.com", password: "anything-long-enough" };

  it("accepts a valid payload", () => {
    expect(loginSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a malformed email", () => {
    expect(loginSchema.safeParse({ ...valid, email: "nope" }).success).toBe(false);
  });

  it("rejects a short password", () => {
    const result = loginSchema.safeParse({ ...valid, password: "short" });

    expect(result.success).toBe(false);
    expect(firstError(result)).toMatch(/valid password/i);
  });

  it("does not enforce the signup password policy", () => {
    // Login must accept whatever an existing account was created with. Applying the
    // signup rules here would lock out anyone whose password predates them, and would
    // leak the policy to an attacker probing addresses.
    const withNoSymbolOrDigit = { ...valid, password: "onlyletters" };

    expect(loginSchema.safeParse(withNoSymbolOrDigit).success).toBe(true);
  });

  it("strips surrounding whitespace from the password", () => {
    // Login trims too, so the two schemas agree: a password can never have leading or
    // trailing spaces on either side of the flow. Consistent, but it does mean a user
    // typing one gets a different string submitted than the one they typed.
    const result = loginSchema.safeParse({ ...valid, password: "  longenough  " });

    expect(result.success).toBe(true);
    expect(result.data?.password).toBe("longenough");
  });

  it("preserves interior spaces in a password", () => {
    // Only the edges are affected; a passphrase with spaces in the middle survives.
    const result = loginSchema.safeParse({ ...valid, password: "pass word here" });

    expect(result.success).toBe(true);
    expect(result.data?.password).toBe("pass word here");
  });
});

describe("repoCreateSchema", () => {
  it.each([
    "https://github.com/example/project",
    "https://github.com/example/project/",
    "https://github.com/my-org/my.repo",
    "https://github.com/a_b/repo-name",
  ])("accepts %s", (github_url) => {
    expect(repoCreateSchema.safeParse({ github_url }).success).toBe(true);
  });

  it.each([
    ["a non-URL", "not a url", /valid GitHub repository URL/i],
    ["another host", "https://gitlab.com/example/project", /must point to a valid/i],
    ["a bare host", "https://github.com", /must point to a valid/i],
    ["an org without a repo", "https://github.com/example", /must point to a valid/i],
    ["a deeper path", "https://github.com/example/project/tree/main", /must point to a valid/i],
    ["plain http", "http://github.com/example/project", /must point to a valid/i],
    ["a lookalike host", "https://github.com.evil.example/example/project", /must point to a valid/i],
  ])("rejects %s", (_label, github_url, expected) => {
    const result = repoCreateSchema.safeParse({ github_url });

    expect(result.success).toBe(false);
    expect(firstError(result)).toMatch(expected);
  });

  it("rejects a missing field", () => {
    expect(repoCreateSchema.safeParse({}).success).toBe(false);
  });

  it("trims surrounding whitespace", () => {
    // A pasted URL commonly arrives with a trailing space from the clipboard. The trim
    // now runs before the URL check, so `z.url()` and the path refine both see the
    // trimmed value.
    const result = repoCreateSchema.safeParse({
      github_url: "  https://github.com/example/project  ",
    });

    expect(result.success).toBe(true);
    expect(result.data?.github_url).toBe("https://github.com/example/project");
  });

  it("requires https rather than merely allowing it", () => {
    // `http://` matches the `[\w.-]+/[\w.-]+` shape, so only the scheme check rejects it.
    expect(repoCreateSchema.safeParse({ github_url: "http://github.com/a/b" }).success).toBe(
      false,
    );
  });
});

describe("contactSchema", () => {
  const valid = {
    category: "bug",
    name: "Ada Lovelace",
    email: "ada@example.com",
    message: "The graph view does not render on a large repository.",
    illume_hp: "",
  };

  it("accepts a valid payload", () => {
    expect(contactSchema.safeParse(valid).success).toBe(true);
  });

  it("accepts every category the dropdown offers", () => {
    // The options are rendered from `contactCategories`, and the schema's enum is built
    // from the same list -- so a category added to the UI but not the schema would fail
    // here rather than silently 422-ing against the server.
    for (const { value } of contactCategories) {
      expect(contactSchema.safeParse({ ...valid, category: value }).success).toBe(true);
    }
  });

  it("rejects an empty category", () => {
    // An untouched select submits its placeholder value, and that must not be accepted
    // as though the visitor had chosen something.
    expect(firstError(contactSchema.safeParse({ ...valid, category: "" }))).toMatch(
      /pick a category/i,
    );
  });

  it("rejects an unknown category", () => {
    expect(contactSchema.safeParse({ ...valid, category: "urgent" }).success).toBe(false);
  });

  it("accepts a name of exactly two characters", () => {
    expect(contactSchema.safeParse({ ...valid, name: "Al" }).success).toBe(true);
  });

  it("rejects a one-character name", () => {
    expect(firstError(contactSchema.safeParse({ ...valid, name: "A" }))).toMatch(
      /at least 2 characters/i,
    );
  });

  it("rejects a malformed email", () => {
    expect(firstError(contactSchema.safeParse({ ...valid, email: "not-an-email" }))).toMatch(
      /valid email/i,
    );
  });

  it("rejects a message below the minimum length", () => {
    expect(firstError(contactSchema.safeParse({ ...valid, message: "too short" }))).toMatch(
      /at least 10 characters/i,
    );
  });

  it("accepts a multi-line message", () => {
    // The message field is a textarea; rejecting a line break would refuse the most
    // ordinary bug report. The server has the same requirement, and this pins the client
    // half of it.
    const result = contactSchema.safeParse({
      ...valid,
      message: "Steps:\n1. Open the graph\n2. Resize the window",
    });

    expect(result.success).toBe(true);
  });

  it("trims surrounding whitespace from the message", () => {
    const result = contactSchema.safeParse({ ...valid, message: "   padded message   " });

    expect(result.data?.message).toBe("padded message");
  });

  it("accepts any honeypot value", () => {
    // The decoy is checked on the server, which discards the submission. Rejecting it
    // here would both tell a bot which field caught it and lock out a visitor whose
    // browser autofilled it, so the client must remain indifferent to its contents.
    expect(contactSchema.safeParse({ ...valid, illume_hp: "anything at all" }).success).toBe(
      true,
    );
  });

  it("declares the honeypot as a field so the form always submits it", () => {
    // A body built by picking only the visible fields would leave the decoy present in
    // the markup and absent on the wire, quietly disabling the only abuse control there
    // is.
    expect(Object.keys(contactSchema.shape)).toContain("illume_hp");
  });
});
