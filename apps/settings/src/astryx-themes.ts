import { defineTheme } from "@astryxdesign/core/theme";

export const localRagTheme = defineTheme({
  name: "local-rag",
  motion: { character: "crisp" },
  tokens: {
    "--color-text-primary": ["#2C2C2B", "#FFFFFF"],
    "--color-text-secondary": ["#7D7A75", "#C5C5C5"],
    "--color-background-body": "#FFFFFF",
    "--color-background-surface": "#F9F8F7",
    "--color-background-muted": "#F9F8F7",
    "--color-border": "rgba(42,28,0,0.07)",
    "--color-border-emphasized": "rgba(28,19,1,0.11)",
    "--color-accent": "#2383E2",
    "--color-on-accent": ["#FFFFFF", "#000000"],
    "--color-error": ["#E03E3E", "#FF99A4"],
    "--radius-element": "6px",
    "--radius-container": "10px",
    "--radius-page": "12px",
    "--size-element-md": "28px",
    "--size-element-sm": "24px",
    "--font-family-body": '"Segoe UI Variable Text", "Segoe UI", "Yu Gothic UI", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Noto Sans CJK JP", system-ui, sans-serif',
    "--font-family-heading": '"Segoe UI Variable Text", "Segoe UI", "Yu Gothic UI", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Noto Sans CJK JP", system-ui, sans-serif',
  },
});

export const themes = { "local-rag": localRagTheme };
export const defaultThemeSlug = "local-rag" as const;
