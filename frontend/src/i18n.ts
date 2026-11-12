// UI language: Russian strings are the keys, English translations live in i18n.en.json.
// Switching language reloads the page, so module-level t() calls are fine.
import en from "./i18n.en.json";

export type Lang = "ru" | "en";
const LANG_KEY = "dm_lang";
const THEME_KEY = "dm_theme";

export const LANG: Lang = (localStorage.getItem(LANG_KEY) as Lang) === "en" ? "en" : "ru";
const dict = en as Record<string, string>;

export function t(s: string): string {
  return LANG === "en" ? dict[s] ?? s : s;
}

/** t() with positional placeholders {0}, {1}… */
export function tf(s: string, ...args: unknown[]): string {
  return t(s).replace(/\{(\d+)\}/g, (_, i) => String(args[Number(i)] ?? ""));
}

export function setLang(l: Lang) {
  localStorage.setItem(LANG_KEY, l);
  location.reload();
}

export const LOCALE = LANG === "en" ? "en-GB" : "ru-RU";

// ---------- theme ----------
export type Theme = "dark" | "light";
export function getTheme(): Theme {
  return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
}
export function applyTheme(th: Theme = getTheme()) {
  document.documentElement.dataset.theme = th;
}
export function setTheme(th: Theme) {
  localStorage.setItem(THEME_KEY, th);
  applyTheme(th);
  window.dispatchEvent(new CustomEvent("dm-theme", { detail: th }));
}
