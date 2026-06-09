/**
 * Stroke icons (ported from `components.jsx Icons`) — inherit `currentColor`, so
 * color always comes from the surrounding token-driven CSS (INV-14, no hex here).
 *
 * Only the subset the Board + chrome need is ported; later slices port more.
 */
import type { SVGProps } from "react";

interface IcoProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

function base({ size = 18, ...rest }: IcoProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...rest,
  };
}

/** A filled-glyph icon (currentColor fill, no stroke). */
function baseFill({ size = 18, ...rest }: IcoProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "currentColor",
    stroke: "none",
    ...rest,
  };
}

export const BoardIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <rect x="3" y="3" width="7" height="18" rx="1.5" />
    <rect x="14" y="3" width="7" height="11" rx="1.5" />
  </svg>
);
export const RunsIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M5 12h4l2-7 3 14 2-7h3" />
  </svg>
);
export const FlowIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <rect x="3" y="4" width="6" height="4" rx="1" />
    <rect x="15" y="9" width="6" height="4" rx="1" />
    <rect x="3" y="16" width="6" height="4" rx="1" />
    <path d="M9 6h3a2 2 0 0 1 2 2v0M9 18h3a2 2 0 0 0 2-2v-1" />
  </svg>
);
export const SettingsIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
  </svg>
);
export const PlusIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const SearchIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);
export const RefreshIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5" />
  </svg>
);
export const SunIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" />
  </svg>
);
export const MoonIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </svg>
);
export const ChevDownIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
export const DotsIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <circle cx="5" cy="12" r="1.6" />
    <circle cx="12" cy="12" r="1.6" />
    <circle cx="19" cy="12" r="1.6" />
  </svg>
);
export const ClockIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);
export const BoltIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <path d="M13 2 4 13h6l-1 9 9-11h-6z" />
  </svg>
);
export const PauseIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <rect x="7" y="5" width="3.4" height="14" rx="1.2" />
    <rect x="13.6" y="5" width="3.4" height="14" rx="1.2" />
  </svg>
);
export const CheckIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);
export const XIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);
export const PrIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="6" cy="18" r="2.5" />
    <circle cx="18" cy="18" r="2.5" />
    <path d="M6 8.5v7M18 15.5V12a3 3 0 0 0-3-3h-3l2-2m0 4-2-2" />
  </svg>
);
export const GitHubIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.49l-.01-1.7c-2.78.62-3.37-1.22-3.37-1.22-.46-1.18-1.11-1.5-1.11-1.5-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.9 1.57 2.36 1.12 2.94.85.09-.66.35-1.12.63-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.7 0 0 .84-.28 2.75 1.05a9.3 9.3 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.4.2 2.44.1 2.7.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.8-4.57 5.06.36.32.68.95.68 1.92l-.01 2.84c0 .27.18.59.69.49A10.03 10.03 0 0 0 22 12.25C22 6.58 17.52 2 12 2Z" />
  </svg>
);
export const ExtIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M14 5h5v5M19 5l-8 8M12 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" />
  </svg>
);
export const PlayIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <path d="M7 5.5v13l11-6.5z" />
  </svg>
);
export const StopIcon = (p: IcoProps) => (
  <svg {...baseFill(p)} aria-hidden>
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
  </svg>
);
export const FilterIcon = (p: IcoProps) => (
  <svg {...base(p)} aria-hidden>
    <path d="M3 5h18l-7 8v5l-4 2v-7z" />
  </svg>
);
