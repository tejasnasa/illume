/**
 * Turns a failed HTTP response into an Error carrying the backend's own reason.
 * @module ApiError
 */

/**
 * Flattens FastAPI's `detail` field into a single displayable line.
 *
 * `detail` is a plain string for errors the API raises itself, but a **list** of
 * objects for a 422 from request validation, so both shapes are handled here.
 *
 * @param body - Parsed response body, of unknown shape.
 * @returns The extracted reason, or null when the body carries none.
 */
function extractDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;

  const { detail } = body as { detail?: unknown };

  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object" && typeof (item as { msg?: unknown }).msg === "string"
          ? (item as { msg: string }).msg
          : null,
      )
      .filter((message): message is string => Boolean(message));

    if (messages.length) return messages.join(" ");
  }

  return null;
}

/**
 * Builds the Error to surface for a non-OK response.
 *
 * FastAPI serializes `HTTPException` as `{"detail": ...}`, never `{"message": ...}`.
 * Every call site that read `.message` therefore fell through to its generic fallback
 * and discarded the reason the server had actually sent — "Email already registered"
 * arriving as "Something went wrong", which is precisely the message that would have
 * told the user to log in instead.
 *
 * `res.json()` throws on a body that is not JSON (an error page from a proxy, a
 * dropped connection), which is why the parse is guarded: unguarded, the parse
 * failure's own message (`Unexpected end of JSON input`) is what reaches the user.
 *
 * @param res - A response whose `ok` is false.
 * @param fallback - Message to use when the body carries no usable reason.
 * @returns An Error whose message is safe to display.
 */
export default async function apiError(
  res: Response,
  fallback: string,
): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(extractDetail(body) ?? fallback);
}
