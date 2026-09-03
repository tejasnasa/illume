/**
 * Auth gate redirecting between protected and public routes.
 * @module AuthProxy
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const protectedRoutes = ["/dashboard", "/repo"];
const publicRoutes = ["/login", "/"];

/**
 * Routes unauthenticated users to login and logged-in users to the dashboard.
 *
 * @param req - Incoming Next.js request with cookies and URL.
 * @returns Redirect to login/dashboard, or continuation to the page.
 */
export function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;
  // Prefix match so nested /repo/[id] pages stay protected.
  const isProtectedRoute = protectedRoutes.some((route) =>
    path.startsWith(route),
  );
  const isPublicRoute = publicRoutes.includes(path);

  const token = req.cookies.get("access_token")?.value;
  const hasSession = Boolean(token);

  if (isProtectedRoute && !hasSession) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  if (isPublicRoute && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }

  return NextResponse.next();
}

/**
 * Default export alias so Next.js picks up the proxy entrypoint.
 *
 * @param req - Incoming Next.js request.
 * @returns Proxy result from {@link proxy}.
 */
export default proxy;

/**
 * Matcher skipping API, static assets, and images from auth checks.
 */
export const config = {
  matcher: ["/((?!api|_next/static|_next/image|.*\\.png$).*)"],
};
