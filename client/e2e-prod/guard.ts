/**
 * Target assertions for the production smoke suite.
 *
 * This suite drives the real deployed site, so the first thing it must prove is that it
 * is aimed at the real deployed site -- and that it cannot be aimed anywhere else. These
 * rules are the whole safety story, which is why they live in a module of their own:
 * pure functions with no Playwright import, so they can be exercised directly when the
 * rules change rather than only by running the suite against production.
 */

export interface TargetInput {
  baseUrl: string;
  apiUrl: string;
  webHosts: Set<string>;
  apiHosts: Set<string>;
}

/**
 * Throws unless both origins are https and their hostnames are exactly allowlisted.
 *
 * @param input - The two origins to check and the host set each is checked against.
 */
export function assertAllowedTarget({
  baseUrl,
  apiUrl,
  webHosts,
  apiHosts,
}: TargetInput): void {
  const web = parse(baseUrl, "SMOKE_BASE_URL");
  const api = parse(apiUrl, "SMOKE_API_URL");

  assertAllowedHost(web, webHosts, "SMOKE_BASE_URL");
  assertAllowedHost(api, apiHosts, "SMOKE_API_URL");

  if (web.hostname.toLowerCase() === api.hostname.toLowerCase()) {
    throw new Error(
      `SMOKE_BASE_URL and SMOKE_API_URL both resolve to ${web.hostname}. This suite exists ` +
        "to exercise the cross-host session cookie and the CORS allow-list, so pointing both " +
        "at one origin would leave the behaviour it is here to verify untested.",
    );
  }

  if (registrableDomain(web.hostname) !== registrableDomain(api.hostname)) {
    throw new Error(
      `SMOKE_BASE_URL (${web.hostname}) and SMOKE_API_URL (${api.hostname}) are on different ` +
        "registrable domains. The session cookie is SameSite=Lax, so the browser would not " +
        "attach it to a cross-site request and every authenticated spec would fail for a " +
        "reason that has nothing to do with the application.",
    );
  }
}

/** Parses a URL, naming the variable rather than surfacing a bare TypeError. */
function parse(raw: string, variable: string): URL {
  try {
    return new URL(raw);
  } catch {
    throw new Error(`${variable} is not a valid URL: ${JSON.stringify(raw)}`);
  }
}

/** Refuses anything that is not https and exactly allowlisted. */
function assertAllowedHost(url: URL, allowed: Set<string>, variable: string): void {
  if (url.protocol !== "https:") {
    throw new Error(
      `${variable} must be https, got ${url.protocol}//${url.host}. The deployed site is ` +
        "https, so an http origin is either the wrong target or would be blocked as mixed " +
        "content before any assertion ran.",
    );
  }

  const host = url.hostname.toLowerCase();

  if (host === "localhost" || host.endsWith(".localhost") || isBareIp(host)) {
    throw new Error(
      `${variable} points at ${host}. This suite never runs against a local or bare-IP target.`,
    );
  }

  // Set membership, never a substring test: `illume.tejasnasa.me.attacker.tld` and
  // `evil-illume.tejasnasa.me` both *contain* an allowlisted host and must be refused.
  if (!allowed.has(host)) {
    throw new Error(
      `${variable} host ${JSON.stringify(host)} is not allowlisted (allowed: ` +
        `${[...allowed].join(", ")}). Matching is exact, so a lookalike that merely contains ` +
        "an allowlisted host is refused.",
    );
  }
}

/** True for IPv4 literals and for IPv6 in either bracketed or bare form. */
function isBareIp(host: string): boolean {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(":");
}

/**
 * The last two labels of a hostname.
 *
 * Deliberately not a public-suffix-accurate eTLD+1 -- it is used only to compare two
 * hosts that must be same-site, which two labels answers correctly for every domain this
 * suite will realistically be pointed at.
 */
export function registrableDomain(host: string): string {
  return host.toLowerCase().split(".").slice(-2).join(".");
}
