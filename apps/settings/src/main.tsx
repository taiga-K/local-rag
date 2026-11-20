import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Theme } from "@astryxdesign/core/theme";
import { themes, defaultThemeSlug } from "./astryx-themes";
import { App } from "./App";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "./motion.css";
import "./shell.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("root is missing");
}
createRoot(root).render(
  <StrictMode>
    <Theme theme={themes[defaultThemeSlug]} mode="light">
      <App />
    </Theme>
  </StrictMode>,
);
