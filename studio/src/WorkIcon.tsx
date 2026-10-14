import type { ReactNode } from "react";
export function WorkIcon({ name, size = 17 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    folder: (
      <path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    ),
    stack: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="3" />
        <path d="M4 10h16M9 10v10" />
      </>
    ),
    review: (
      <>
        <rect x="5" y="3" width="14" height="18" rx="2" />
        <path d="m8 11 3 3 5-6M9 18h6" />
      </>
    ),
    check: <path d="m5 12 4.5 4.5L19 7" />,
    activity: <path d="M2 12h5l3-8 4 16 3-8h5" />,
    warning: (
      <>
        <path d="m12 3 10 18H2Z" />
        <path d="M12 9v5m0 3v.1" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M19.5 11a8 8 0 0 0-14-5M4.5 13a8 8 0 0 0 14 5" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="2.5" />
        <circle cx="15" cy="17" r="2.5" />
      </>
    ),
    code: <path d="m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    branch: (
      <>
        <circle cx="6" cy="5" r="2" />
        <circle cx="18" cy="6" r="2" />
        <circle cx="6" cy="19" r="2" />
        <path d="M6 7v10M18 8c0 6-12 2-12 8" />
      </>
    ),
    terminal: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="m7 8 4 4-4 4m6 0h4" />
      </>
    ),
    chevron: <path d="m9 5 7 7-7 7" />,
    download: <path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.stack}
    </svg>
  );
}
