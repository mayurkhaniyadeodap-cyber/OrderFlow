import { useCallback, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "orderflow.theme";

function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light"; // storage blocked: the app still works, the choice just is not remembered
  }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/** Runs before the first render so a dark-theme user never sees a flash of the light theme. */
export function initTheme() {
  applyTheme(storedTheme());
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* not remembered, still applied */
    }
  }, [theme]);
  return [theme, toggle];
}
