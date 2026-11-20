import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Theme } from "@astryxdesign/core/theme";
import { themes, defaultThemeSlug } from "./astryx-themes";
import { App } from "./App";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "./motion.css";
import "./shell.css";

const storedTheme = window.localStorage.getItem("local-rag-theme");
const themeMode = storedTheme === "dark" || storedTheme === "light" || storedTheme === "system" ? storedTheme : "light";
if (storedTheme === "dark" || storedTheme === "light" || storedTheme === "system") {
  document.documentElement.dataset.theme = storedTheme;
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("root is missing");
}
createRoot(root).render(
  <StrictMode>
    <Theme theme={themes[defaultThemeSlug]} mode={themeMode}>
      <App />
    </Theme>
  </StrictMode>,
);
