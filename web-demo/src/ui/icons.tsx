// A small, consistent icon set. Stroke icons at 1.6 keep the UI technical
// rather than decorative.
import type { JSX } from 'react';

type P = { size?: number; className?: string };

const wrap = (path: JSX.Element, box = 24) => ({ size = 16, className }: P) => (
  <svg width={size} height={size} viewBox={`0 0 ${box} ${box}`} fill="none"
       stroke="currentColor" strokeWidth={1.7} strokeLinecap="round"
       strokeLinejoin="round" className={className} aria-hidden="true">
    {path}
  </svg>
);

export const IconMap = wrap(<><path d="M9 4 3 6.5v13L9 17l6 2.5 6-2.5v-13L15 6.5 9 4Z"/><path d="M9 4v13M15 6.5v13"/></>);
export const IconAlert = wrap(<><path d="M12 3 2.5 19.5h19L12 3Z"/><path d="M12 9.5v4.5M12 17h.01"/></>);
export const IconDispatch = wrap(<><rect x="3" y="4" width="6" height="16" rx="1.5"/><rect x="11" y="4" width="6" height="9" rx="1.5"/><path d="M19 4h2v16h-2"/></>);
export const IconTasks = wrap(<><rect x="4" y="3" width="16" height="18" rx="2"/><path d="m8.5 10 2 2 4-4M8.5 16h7"/></>);
export const IconTruck = wrap(<><path d="M2 7h11v9H2zM13 10h4l3 3v3h-7z"/><circle cx="6" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/></>);
export const IconUsers = wrap(<><circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><path d="M16 11.5a3 3 0 0 0 0-6M18 20c0-2.4-1-4.2-2.5-5.2"/></>);
export const IconWrench = wrap(<><path d="M15.5 5.5a4.5 4.5 0 0 0-6 5.9L4 17l3 3 5.6-5.5a4.5 4.5 0 0 0 5.9-6l-2.7 2.7-2.5-.5-.5-2.5 2.7-2.7Z"/></>);
export const IconHistory = wrap(<><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v4h4"/><path d="M12 7.5V12l3 2"/></>);
export const IconZone = wrap(<><path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11Z"/><circle cx="12" cy="10" r="2.6"/></>);
export const IconFuel = wrap(<><path d="M4 20V5a2 2 0 0 1 2-2h5a2 2 0 0 1 2 2v15"/><path d="M3 20h11"/><path d="M13 9h3l2 2v6a1.8 1.8 0 1 1-3.6 0V13H13"/><path d="M5 8h7"/></>);
export const IconShield = wrap(<><path d="M12 3 4.5 6v6c0 4.6 3.1 8.1 7.5 9 4.4-.9 7.5-4.4 7.5-9V6L12 3Z"/><path d="m9 12 2 2 4-4"/></>);
export const IconIncident = wrap(<><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16h.01"/></>);
export const IconCoin = wrap(<><ellipse cx="12" cy="6.5" rx="8" ry="3.2"/><path d="M4 6.5v11c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2v-11"/><path d="M4 12c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2"/></>);
export const IconChart = wrap(<><path d="M4 20V4M4 20h16"/><rect x="7.5" y="12" width="3" height="5" rx=".6"/><rect x="12.5" y="8" width="3" height="9" rx=".6"/><rect x="17" y="14" width="3" height="3" rx=".6"/></>);
export const IconLeaf = wrap(<><path d="M20 4c0 9-5.5 13-11 13a5 5 0 0 1-5-5C4 6.5 11 4 20 4Z"/><path d="M4 20c2-5 5-8 9-10"/></>);
export const IconSpark = wrap(<><path d="m12 3 1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4L12 3Z"/><path d="M18.5 16.5 19.3 19l2.5.8-2.5.8-.8 2.4-.8-2.4-2.5-.8 2.5-.8.8-2.5Z"/></>);
export const IconSettings = wrap(<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z"/></>);
export const IconSearch = wrap(<><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></>);
export const IconBell = wrap(<><path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6Z"/><path d="M13.7 20a2 2 0 0 1-3.4 0"/></>);
export const IconClose = wrap(<><path d="m6 6 12 12M18 6 6 18"/></>);
export const IconChevron = wrap(<><path d="m9 5 7 7-7 7"/></>);
export const IconPlus = wrap(<><path d="M12 5v14M5 12h14"/></>);
export const IconCheck = wrap(<><path d="m4.5 12.5 5 5 10-11"/></>);
export const IconPlay = wrap(<><path d="M6.5 4.5 19 12 6.5 19.5v-15Z"/></>);
export const IconPause = wrap(<><rect x="6" y="4.5" width="4" height="15" rx="1"/><rect x="14" y="4.5" width="4" height="15" rx="1"/></>);
export const IconZoomIn = wrap(<><path d="M12 6v12M6 12h12"/></>);
export const IconZoomOut = wrap(<><path d="M6 12h12"/></>);
export const IconCompass = wrap(<><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5.5-5.5 2 2-5.5 5.5-2Z"/></>);
export const IconFit = wrap(<><path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/></>);
export const IconLayers = wrap(<><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3.5 12.5 8.5 4.7 8.5-4.7"/><path d="m3.5 16.5 8.5 4.7 8.5-4.7"/></>);
export const IconRuler = wrap(<><rect x="2.5" y="8" width="19" height="8" rx="1.5" transform="rotate(-12 12 12)"/><path d="M7 9.5v2M10.5 8.7v3M14 7.9v2M17.5 7v3"/></>);
export const IconRoute = wrap(<><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.5 6H14a3.5 3.5 0 0 1 0 7h-4a3.5 3.5 0 0 0 0 7h5.5"/></>);
export const IconSun = wrap(<><circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/></>);
export const IconMoon = wrap(<><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/></>);
export const IconLogout = wrap(<><path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H15"/><path d="M11 16.5 15.5 12 11 7.5M15.5 12H4"/></>);
export const IconDrag = wrap(<><circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/></>);
export const IconTrash = wrap(<><path d="M4 7h16M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2"/><path d="M6.5 7 7.5 20h9L17.5 7"/><path d="M10.5 11v5M13.5 11v5"/></>);
export const IconDownload = wrap(<><path d="M12 4v11M7.5 11 12 15.5 16.5 11"/><path d="M4.5 19.5h15"/></>);
export const IconClock = wrap(<><circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 2"/></>);
export const IconPhone = wrap(<><path d="M6.5 3.5h3l1.5 4-2 1.5a12 12 0 0 0 6 6l1.5-2 4 1.5v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4.5 5.7a2 2 0 0 1 2-2.2Z"/></>);
export const IconCamera = wrap(<><path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2L8 4.5h8L17.5 7h2A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-9Z"/><circle cx="12" cy="13" r="3.5"/></>);
export const IconAward = wrap(<><circle cx="12" cy="9" r="5.5"/><path d="m8.5 13.5-1.5 7 5-2.5 5 2.5-1.5-7"/></>);
export const IconTrendUp = wrap(<><path d="M4 16.5 9.5 11l3.5 3.5L20 7"/><path d="M15 7h5v5"/></>);
export const IconTrendDown = wrap(<><path d="M4 7.5 9.5 13l3.5-3.5L20 17"/><path d="M15 17h5v-5"/></>);
export const IconBattery = wrap(<><rect x="2.5" y="8" width="16" height="9" rx="2"/><path d="M21 11.5v2.5"/><rect x="4.5" y="10" width="6" height="5" rx=".8" fill="currentColor" stroke="none"/></>);
export const IconDoc = wrap(<><path d="M6 3h7l5 5v13H6V3Z"/><path d="M13 3v5h5"/><path d="M9 13h6M9 17h4"/></>);
export const IconFlag = wrap(<><path d="M5 21V4M5 5h10l-1.5 3L15 11H5"/></>);
export const IconMessage = wrap(<><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H9l-5 4V5.5Z"/></>);
export const IconEye = wrap(<><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></>);
export const IconGrid = wrap(<><rect x="3.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.4"/></>);
export const IconList = wrap(<><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/></>);
export const IconCalendar = wrap(<><rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/></>);
export const IconBuilding = wrap(<><path d="M4 21V5.5A1.5 1.5 0 0 1 5.5 4h7A1.5 1.5 0 0 1 14 5.5V21"/><path d="M14 10h4.5A1.5 1.5 0 0 1 20 11.5V21M2.5 21h19"/><path d="M7 8h4M7 12h4M7 16h4"/></>);
export const IconRefresh = wrap(<><path d="M20 11.5a8 8 0 1 0-.6 4.5"/><path d="M20 4v7h-7"/></>);
