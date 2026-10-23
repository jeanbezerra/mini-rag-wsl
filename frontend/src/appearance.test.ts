import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';
import {
  darkTheme, lightTheme, parseAppearancePreference, preferenceFromStorageEvent,
  readAppearancePreference, resolveAppearance, saveAppearancePreference,
} from './appearance';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const storageKey = html.match(/data-appearance-storage-key="([^"]+)"/)![1];
const bootstrap = readFileSync(new URL('../public/appearance-init.js', import.meta.url), 'utf8');

function contrast(foreground: string, background: string): number {
  const luminance = (hex: string) => {
    const rgb = hex.slice(1).match(/../g)!.map((part) => parseInt(part, 16) / 255)
      .map((value) => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

function firstPaint(saved: unknown, systemDark: boolean, denied = false) {
  const root = { dataset: { appearanceStorageKey: storageKey, theme: '' }, style: { colorScheme: '', backgroundColor: '', color: '' } };
  let metaColor = '';
  runInNewContext(bootstrap, {
    window: {
      localStorage: { getItem: (key: string) => { expect(key).toBe(storageKey); if (denied) throw new Error('Denied'); return saved; } },
      matchMedia: (query: string) => { expect(query).toBe('(prefers-color-scheme: dark)'); return { matches: systemDark }; },
    },
    document: { documentElement: root, querySelector: () => ({ setAttribute: (_name: string, value: string) => { metaColor = value; } }) },
  });
  return { root, metaColor };
}

describe('local appearance preference', () => {
  it('uses only the supported preferences and defaults invalid stored data to the system', () => {
    expect(parseAppearancePreference('light')).toBe('light');
    expect(parseAppearancePreference('dark')).toBe('dark');
    for (const value of ['system', null, undefined, 'auto', 'DARK', '{"theme":"dark"}', true]) {
      expect(parseAppearancePreference(value)).toBe('system');
    }
  });

  it('follows system changes only while the system preference is selected', () => {
    expect(resolveAppearance('system', false)).toBe('light');
    expect(resolveAppearance('system', true)).toBe('dark');
    for (const systemDark of [true, false]) {
      expect(resolveAppearance('light', systemDark)).toBe('light');
      expect(resolveAppearance('dark', systemDark)).toBe('dark');
    }
  });

  it('persists the preference under the single key configured in HTML', () => {
    const saved = new Map<string, string>();
    const storage = { getItem: (key: string) => saved.get(key) ?? null, setItem: (key: string, value: string) => saved.set(key, value) };
    for (const preference of ['light', 'dark', 'system'] as const) {
      saveAppearancePreference(storageKey, preference, storage);
      expect(readAppearancePreference(storageKey, storage)).toBe(preference);
    }
    expect([...saved.keys()]).toEqual(['mini-rag.appearance']);
  });

  it('keeps storage failure and missing storage non-fatal', () => {
    const denied = { getItem: () => { throw new Error('Denied'); }, setItem: () => { throw new Error('Quota'); } };
    expect(readAppearancePreference(storageKey, denied)).toBe('system');
    expect(readAppearancePreference(storageKey)).toBe('system');
    expect(() => saveAppearancePreference(storageKey, 'dark', denied)).not.toThrow();
    expect(() => saveAppearancePreference(storageKey, 'dark')).not.toThrow();
  });

  it('synchronizes other tabs, resets removed values, and ignores unrelated storage events', () => {
    expect(preferenceFromStorageEvent({ key: storageKey, newValue: 'dark' }, storageKey)).toBe('dark');
    expect(preferenceFromStorageEvent({ key: storageKey, newValue: 'light' }, storageKey)).toBe('light');
    expect(preferenceFromStorageEvent({ key: storageKey, newValue: null }, storageKey)).toBe('system');
    expect(preferenceFromStorageEvent({ key: null, newValue: null }, storageKey)).toBe('system');
    expect(preferenceFromStorageEvent({ key: storageKey, newValue: 'invalid' }, storageKey)).toBe('system');
    expect(preferenceFromStorageEvent({ key: 'mini-rag.conversations', newValue: 'dark' }, storageKey)).toBeUndefined();
  });
});

describe('CSP-compatible first paint', () => {
  it('loads the external bootstrap before the application module', () => {
    expect(html.indexOf('<script src="/appearance-init.js">')).toBeLessThan(html.indexOf('<script type="module"'));
  });

  it.each([
    ['light', true], ['dark', false], ['system', true], ['system', false], [null, true], ['invalid', false],
  ] as const)('matches the React theme for stored %s and system dark %s', (saved, systemDark) => {
    const { root, metaColor } = firstPaint(saved, systemDark);
    const resolved = resolveAppearance(parseAppearancePreference(saved), systemDark);
    const theme = resolved === 'dark' ? darkTheme : lightTheme;
    expect(root.dataset.theme).toBe(resolved);
    expect(root.style.colorScheme).toBe(resolved);
    expect(root.style.backgroundColor).toBe(theme.colorNeutralBackground2);
    expect(root.style.color).toBe(theme.colorNeutralForeground1);
    expect(metaColor).toBe(theme.colorNeutralBackground2);
  });

  it('can render the system dark surface before React even when storage access is denied', () => {
    expect(firstPaint('light', true, true).root.dataset.theme).toBe('dark');
  });
});

describe('brand contrast in both themes', () => {
  for (const [name, theme] of [['light', lightTheme], ['dark', darkTheme]] as const) {
    it(`${name}: primary actions retain readable text in every interactive state`, () => {
      for (const background of [theme.colorBrandBackground, theme.colorBrandBackgroundHover, theme.colorBrandBackgroundPressed, theme.colorBrandBackgroundSelected]) {
        expect(contrast(theme.colorNeutralForegroundOnBrand, background)).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`${name}: compound controls retain readable indicators in every interactive state`, () => {
      for (const background of [theme.colorCompoundBrandBackground, theme.colorCompoundBrandBackgroundHover, theme.colorCompoundBrandBackgroundPressed]) {
        expect(contrast(theme.colorNeutralForegroundInverted, background)).toBeGreaterThanOrEqual(3);
      }
    });

    it(`${name}: links remain readable over the page and card surfaces`, () => {
      for (const foreground of [theme.colorBrandForegroundLink, theme.colorBrandForegroundLinkHover, theme.colorBrandForegroundLinkPressed, theme.colorBrandForegroundLinkSelected]) {
        for (const background of [theme.colorNeutralBackground1, theme.colorNeutralBackground2, theme.colorNeutralBackground3]) {
          expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
        }
      }
    });

    it(`${name}: small error and warning copy remains readable on document cards and notices`, () => {
      for (const [foreground, tintedSurface] of [
        [theme.colorStatusDangerForeground1, theme.colorStatusDangerBackground1],
        [theme.colorStatusWarningForeground1, theme.colorStatusWarningBackground1],
      ]) {
        for (const background of [theme.colorNeutralBackground1, theme.colorNeutralBackground2, theme.colorNeutralBackground3, tintedSurface]) {
          expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
        }
      }
    });
  }
});
