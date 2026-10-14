/// <reference types="vite/client" />

/** The release version from package.json, injected at build time. */
declare const __PARALLAX_VERSION__: string;

/** Optional public pricing JSON from PARALLAX_PRICING at build time; empty when unset. */
declare const __PARALLAX_PRICING__: string;
