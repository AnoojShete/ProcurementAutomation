/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // The OS's own UI font (San Francisco / Segoe UI), like most
        // enterprise tools — nothing to download, and it reads as native.
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Noto Sans",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        // One accent: a plain working blue for primary actions, links and
        // the active nav marker. Everything else is neutral.
        brand: {
          50: "#ddf4ff",
          100: "#b6e3ff",
          200: "#80ccff",
          300: "#54aeff",
          400: "#218bff",
          500: "#0969da",
          600: "#0860ca",
          700: "#0550ae",
          800: "#033d8b",
          900: "#0a3069",
          950: "#002155",
        },
        // Page background vs. panel surface vs. hairlines.
        surface: {
          DEFAULT: "#ffffff",
          subtle: "#f6f8fa",
          muted: "#eff2f5",
          border: "#d1d9e0",
        },
        // Formerly a purple "AI" accent. Kept as a token so existing
        // classes compile, but it's neutral now: model-driven features are
        // presented like any other data, not with their own colour.
        intel: {
          50: "#f6f8fa",
          100: "#d1d9e0",
          300: "#afb8c1",
          400: "#818b98",
          500: "#59636e",
          600: "#59636e",
          700: "#393f46",
        },
        success: { 50: "#dafbe1", 500: "#1f883d", 600: "#1a7f37", 700: "#116329" },
        warning: { 50: "#fff8c5", 500: "#d4a72c", 600: "#9a6700", 700: "#7d4e00" },
        danger: { 50: "#ffebe9", 100: "#ffcecb", 300: "#ff8182", 500: "#cf222e", 600: "#a40e26", 700: "#82071e" },
      },
      fontSize: {
        // 13px is the workhorse size for dense tables and metadata.
        "13": ["0.8125rem", { lineHeight: "1.25rem" }],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(31, 35, 40, 0.04)",
        popover: "0 8px 24px rgba(140, 149, 159, 0.2), 0 0 0 1px rgba(209, 217, 224, 0.6)",
        button: "0 1px 0 0 rgba(31, 35, 40, 0.04)",
      },
      borderRadius: {
        // Tight, consistent corners. rounded-lg/xl in page code resolve to
        // the same 6px as rounded-md.
        lg: "0.375rem",
        xl: "0.375rem",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-in-right": { from: { transform: "translateX(-8px)", opacity: 0 }, to: { transform: "translateX(0)", opacity: 1 } },
        "slide-up": { from: { transform: "translateY(4px)", opacity: 0 }, to: { transform: "translateY(0)", opacity: 1 } },
      },
      animation: {
        "fade-in": "fade-in 0.12s ease-out",
        "slide-in-right": "slide-in-right 0.15s ease-out",
        "slide-up": "slide-up 0.12s ease-out",
      },
    },
  },
  plugins: [],
};
