/** Build Output API routes keep browser API calls on the Studio origin. */
export function runtimeOrigin(value = "") {
  if (!value) return "";
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    ["localhost", "127.0.0.1", "::1", "[::1]"].includes(url.hostname)
  ) {
    throw new Error(
      "PARALLAX_RUNTIME_URL must be a public HTTPS origin without credentials, paths, or query parameters.",
    );
  }
  return url.origin;
}

export function outputConfig(value = "") {
  const origin = runtimeOrigin(value);
  return {
    version: 3,
    routes: [
      {
        src: "/.*",
        headers: {
          "X-Content-Type-Options": "nosniff",
          "Referrer-Policy": "no-referrer",
          "X-Frame-Options": "DENY",
          "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
          "Content-Security-Policy": `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src ${origin ? "'self'" : "'none'"}; frame-ancestors 'none'; base-uri 'self'; form-action ${origin ? "'self'" : "'none'"}`,
        },
        continue: true,
      },
      {
        src: "/api(?:/(.*))?",
        dest: origin ? `${origin}/api/$1` : "/runtime-unavailable.json",
        headers: { "Cache-Control": "no-store" },
      },
      {
        src: "/assets/.*",
        headers: { "Cache-Control": "public, max-age=31536000, immutable" },
        continue: true,
      },
      {
        src: "/(?!assets/).*",
        headers: { "Cache-Control": "no-cache" },
        continue: true,
      },
      { handle: "filesystem" },
      { src: "/assets/.*", status: 404 },
      { src: "/.*", dest: "/index.html" },
    ],
  };
}
