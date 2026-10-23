// Runs before the first paint without relaxing the script-src CSP.
(() => {
  const root = document.documentElement;
  const key = root.dataset.appearanceStorageKey;
  let preference = 'system';
  try {
    const saved = key && window.localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch { /* Storage may be unavailable; follow the operating system. */ }
  const systemDark = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  root.style.backgroundColor = theme === 'dark' ? '#1f1f1f' : '#fafafa';
  root.style.color = theme === 'dark' ? '#ffffff' : '#242424';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', root.style.backgroundColor);
})();
