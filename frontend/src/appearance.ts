import { createDarkTheme, createLightTheme, type BrandVariants } from '@fluentui/react-components';

export type AppearancePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const brand: BrandVariants = {
  10: '#021311', 20: '#032824', 30: '#074138', 40: '#095247',
  50: '#0c6256', 60: '#0e7366', 70: '#118477', 80: '#159589',
  90: '#25a69a', 100: '#44b6aa', 110: '#63c5ba', 120: '#83d3ca',
  130: '#a3e0d9', 140: '#c2ece7', 150: '#dff6f2', 160: '#f2fcfa',
};

export const lightTheme = createLightTheme(brand);
// White text on the existing teal primary surface remains readable in every state.
Object.assign(lightTheme, {
  colorBrandBackground: brand[60],
  colorBrandBackgroundHover: brand[50],
  colorBrandBackgroundPressed: brand[40],
  colorBrandBackgroundSelected: brand[50],
  colorBrandForeground1: brand[50],
  colorBrandForeground2: brand[40],
  colorBrandForegroundLink: brand[60],
  colorBrandForegroundLinkHover: brand[50],
  colorBrandForegroundLinkPressed: brand[40],
  colorBrandForegroundLinkSelected: brand[50],
  colorCompoundBrandBackground: brand[60],
  colorCompoundBrandBackgroundHover: brand[50],
  colorCompoundBrandBackgroundPressed: brand[40],
  colorBrandStroke1: brand[60],
});

export const darkTheme = createDarkTheme(brand);
// Keep Fluent's on-brand foreground semantic: it is also used by status badges.
// The hover step brightens in dark mode while retaining readable white text.
Object.assign(darkTheme, {
  colorBrandBackground: brand[60],
  colorBrandBackgroundHover: brand[70],
  colorBrandBackgroundPressed: brand[50],
  colorBrandBackgroundSelected: brand[60],
  colorBrandForeground1: brand[110],
  colorBrandForeground2: brand[120],
  colorBrandForegroundLink: brand[110],
  colorBrandForegroundLinkHover: brand[120],
  colorBrandForegroundLinkPressed: brand[100],
  colorBrandForegroundLinkSelected: brand[110],
  // Error copy also appears on neutral document cards, beyond the tinted error surface.
  colorStatusDangerForeground1: darkTheme.colorStatusDangerForeground3,
});

export function parseAppearancePreference(value: unknown): AppearancePreference {
  return value === 'light' || value === 'dark' ? value : 'system';
}

export function resolveAppearance(preference: AppearancePreference, systemDark: boolean): ResolvedTheme {
  return preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
}

// The HTML attribute is also read by the CSP-compatible prepaint script.
export function appearanceStorageKey(): string {
  return typeof document === 'undefined' ? '' : document.documentElement.dataset.appearanceStorageKey ?? '';
}

export function readAppearancePreference(key: string, storage?: Pick<Storage, 'getItem'>): AppearancePreference {
  try {
    return key && storage ? parseAppearancePreference(storage.getItem(key)) : 'system';
  } catch {
    return 'system';
  }
}

export function saveAppearancePreference(key: string, preference: AppearancePreference, storage?: Pick<Storage, 'setItem'>): void {
  try {
    if (key && storage) storage.setItem(key, preference);
  } catch {
    // The current tab can still change its appearance when storage is blocked or full.
  }
}

export function preferenceFromStorageEvent(
  event: Pick<StorageEvent, 'key' | 'newValue'>,
  storageKey: string,
): AppearancePreference | undefined {
  if (!storageKey || (event.key !== storageKey && event.key !== null)) return undefined;
  return parseAppearancePreference(event.newValue);
}
