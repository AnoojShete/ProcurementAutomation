/** @type {import('tailwindcss').Config} */

// Ledger design system (docs/design-direction.md). Colours live in
// src/styles/tokens.css as RGB channels; this maps them to class names.
const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // IBM Plex Sans for all UI text (tabular digits by default, ₹ in
        // latin-ext), Plex Mono for references, Source Serif 4 for item
        // titles only. Self-hosted via @fontsource (CSP is font-src 'self').
        // Family names are quoted inside the string: "Source Serif 4" ends in
        // a number, and an unquoted family like that invalidates the rule.
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SF Mono", "Menlo", "monospace"],
        doc: ['"Source Serif 4"', "Georgia", "Times New Roman", "serif"],
      },
      colors: {
        // Semantic names: use these in new code.
        paper: c("paper"),
        sheet: { DEFAULT: c("sheet"), sunk: c("sheet-sunk") },
        rule: { DEFAULT: c("rule"), mid: c("rule-mid"), strong: c("rule-strong") },
        ink: { DEFAULT: c("ink"), 2: c("ink-2"), 3: c("ink-3") },
        accent: { DEFAULT: c("accent"), hover: c("accent-hover"), tint: c("accent-tint") },

        // Existing names, re-pointed so every page picks up the palette.
        brand: {
          50: c("accent-tint"),
          100: c("accent-tint"),
          200: c("accent-soft"),
          300: c("accent-soft"),
          400: c("accent"),
          500: c("accent"),
          600: c("accent-hover"),
          700: c("accent-hover"),
          800: c("accent-deep"),
          900: c("accent-deep"),
          950: c("accent-deep"),
        },
        surface: {
          DEFAULT: c("sheet"),
          subtle: c("paper"),
          muted: c("sheet-sunk"),
          border: c("rule"),
        },
        // Formerly a purple "AI" accent; neutral ink now.
        intel: {
          50: c("sheet-sunk"),
          100: c("rule"),
          300: c("rule-mid"),
          400: c("ink-3"),
          500: c("ink-3"),
          600: c("ink-2"),
          700: c("ink-2"),
        },
        success: { 50: c("done-tint"), 100: c("done-soft"), 500: c("done"), 600: c("done"), 700: c("done") },
        warning: { 50: c("attention-tint"), 100: c("attention-soft"), 500: c("attention-mid"), 600: c("attention"), 700: c("attention") },
        danger: { 50: c("danger-tint"), 100: c("danger-soft"), 300: c("danger-soft"), 500: c("danger"), 600: c("danger"), 700: c("danger-deep") },

        // Raw Tailwind palettes used directly in page code, re-pointed to the
        // Ledger neutrals and roles. This is what fixes the contrast failures
        // (slate-400 text was 2.56 : 1; it is now ink-3, 5.83 : 1) without a
        // 40-file edit. New code should use the semantic names above.
        slate: {
          50: c("paper"),
          100: c("sheet-sunk"),
          200: c("rule"),
          300: c("rule-mid"),
          400: c("ink-3"),
          500: c("ink-3"),
          600: c("ink-2"),
          700: c("ink-2"),
          800: c("ink"),
          900: c("ink"),
          950: c("ink"),
        },
        emerald: {
          50: c("done-tint"), 100: c("done-tint"), 200: c("done-soft"), 300: c("done-soft"),
          400: c("done"), 500: c("done"), 600: c("done"), 700: c("done"), 800: c("done"), 900: c("done"), 950: c("done"),
        },
        rose: {
          50: c("danger-tint"), 100: c("danger-tint"), 200: c("danger-soft"), 300: c("danger-soft"),
          400: c("danger"), 500: c("danger"), 600: c("danger"), 700: c("danger-deep"), 800: c("danger-deep"), 900: c("danger-deep"),
        },
        red: { 50: c("danger-tint"), 500: c("danger"), 600: c("danger"), 700: c("danger-deep") },
        amber: {
          50: c("attention-tint"), 100: c("attention-tint"), 200: c("attention-soft"), 300: c("attention-soft"),
          400: c("attention-mid"), 500: c("attention-mid"), 600: c("attention"), 700: c("attention"), 800: c("attention"), 900: c("attention"),
        },
        blue: {
          50: c("accent-tint"), 100: c("accent-tint"), 200: c("accent-soft"), 300: c("accent-soft"),
          400: c("accent"), 500: c("accent"), 600: c("accent"), 700: c("accent-hover"), 800: c("accent-deep"), 900: c("accent-deep"),
        },
      },
      fontSize: {
        // The scale (design-direction.md §2). 12px is the floor.
        caption: ["0.75rem", { lineHeight: "1rem" }],
        "13": ["0.8125rem", { lineHeight: "1.25rem" }],
        body: ["0.875rem", { lineHeight: "1.375rem" }],
        heading: ["1rem", { lineHeight: "1.5rem" }],
        title: ["1.25rem", { lineHeight: "1.75rem" }],
        "doc-title": ["1.625rem", { lineHeight: "2rem" }],
        figure: ["1.75rem", { lineHeight: "2rem" }],
      },
      boxShadow: {
        // Floating layers only; page content is flat.
        card: "none",
        button: "none",
        popover: "0 1px 2px rgb(24 33 28 / 0.08), 0 8px 24px rgb(24 33 28 / 0.12)",
      },
      borderRadius: {
        // 2px tags, 4px controls and sections, 8px modals/popovers.
        sm: "0.125rem",
        DEFAULT: "0.25rem",
        md: "0.25rem",
        lg: "0.25rem",
        xl: "0.5rem",
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
        in: "var(--ease-in)",
      },
      transitionDuration: {
        1: "var(--dur-1)",
        2: "var(--dur-2)",
        3: "var(--dur-3)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-in-right": { from: { transform: "translateX(-8px)", opacity: 0 }, to: { transform: "translateX(0)", opacity: 1 } },
        "slide-up": { from: { transform: "translateY(4px)", opacity: 0 }, to: { transform: "translateY(0)", opacity: 1 } },
        // The decision stamp settling onto the paper trail.
        stamp: {
          from: { transform: "scale(1.12) rotate(-4deg)", opacity: 0 },
          to: { transform: "scale(1) rotate(-2deg)", opacity: 1 },
        },
        "delayed-in": { "0%, 60%": { opacity: 0 }, "100%": { opacity: 1 } },
      },
      animation: {
        "fade-in": "fade-in var(--dur-2) var(--ease-out)",
        "slide-in-right": "slide-in-right var(--dur-2) var(--ease-out)",
        "slide-up": "slide-up var(--dur-2) var(--ease-out)",
        stamp: "stamp var(--dur-3) var(--ease-out) both",
        // Spinners appear only after ~150ms, so fast actions don't flicker.
        "delayed-in": "delayed-in 250ms linear both",
      },
    },
  },
  plugins: [],
};
