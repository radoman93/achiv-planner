import { NextRequest, NextResponse } from "next/server";

const PROTECTED = ["/dashboard", "/routes", "/characters", "/calendar", "/onboarding", "/settings"];
const AUTH_PAGES = ["/login", "/register"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasToken = request.cookies.has("access_token");

  // Protected routes — redirect to login if no token
  if (PROTECTED.some((p) => pathname.startsWith(p)) && !hasToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Auth pages — redirect to dashboard if already authenticated
  if (AUTH_PAGES.some((p) => pathname.startsWith(p)) && hasToken) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/routes/:path*",
    "/characters/:path*",
    "/calendar/:path*",
    "/onboarding/:path*",
    "/settings/:path*",
    "/login",
    "/register",
  ],
};
