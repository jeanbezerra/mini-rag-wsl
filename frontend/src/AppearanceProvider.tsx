import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { FluentProvider } from '@fluentui/react-components';
import {
  appearanceStorageKey, darkTheme, lightTheme, preferenceFromStorageEvent,
  readAppearancePreference, resolveAppearance, saveAppearancePreference,
  type AppearancePreference, type ResolvedTheme,
} from './appearance';

interface AppearanceContextValue {
  preference: AppearancePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: AppearancePreference) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function localStorageIfAvailable(): Storage | undefined {
  try { return window.localStorage; } catch { return undefined; }
}

function darkMedia(): MediaQueryList | undefined {
  return typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : undefined;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [preference, updatePreference] = useState<AppearancePreference>(() => readAppearancePreference(appearanceStorageKey(), localStorageIfAvailable()));
  const [systemDark, setSystemDark] = useState(() => darkMedia()?.matches ?? false);
  const resolvedTheme = resolveAppearance(preference, systemDark);
  const theme = resolvedTheme === 'dark' ? darkTheme : lightTheme;

  const setPreference = useCallback((next: AppearancePreference) => {
    updatePreference(next);
    saveAppearancePreference(appearanceStorageKey(), next, localStorageIfAvailable());
  }, []);

  useEffect(() => {
    const media = darkMedia();
    const update = () => setSystemDark(media?.matches ?? false);
    update();
    media?.addEventListener('change', update);
    return () => media?.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const storage = localStorageIfAvailable();
    const update = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== storage) return;
      const next = preferenceFromStorageEvent(event, appearanceStorageKey());
      if (next !== undefined) updatePreference(next);
    };
    window.addEventListener('storage', update);
    return () => window.removeEventListener('storage', update);
  }, []);

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.style.colorScheme = resolvedTheme;
    root.style.backgroundColor = theme.colorNeutralBackground2;
    root.style.color = theme.colorNeutralForeground1;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.colorNeutralBackground2);
  }, [resolvedTheme, theme]);

  const value = useMemo(() => ({ preference, resolvedTheme, setPreference }), [preference, resolvedTheme, setPreference]);
  return (
    <AppearanceContext.Provider value={value}>
      <FluentProvider theme={theme} style={{ minHeight: '100dvh', colorScheme: resolvedTheme }}>
        {children}
      </FluentProvider>
    </AppearanceContext.Provider>
  );
}

export function useAppearance(): AppearanceContextValue {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error('useAppearance requires AppearanceProvider');
  return value;
}
