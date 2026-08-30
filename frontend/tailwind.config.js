/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      colors: {
        // Deep navy/blue brand family — primary CTAs, active nav, links.
        brand: {
          50: "#eef3fb",
          100: "#d9e5f5",
          200: "#b3caeb",
          300: "#82a9dc",
          400: "#4f83c9",
          500: "#2f63ac",
          600: "#204a87",
          700: "#1a3b6d",
          800: "#152f57",
          900: "#0f2140",
          950: "#0a1730",
        },
        // Soft neutral surfaces (page background vs. card surface).
        surface: {
          DEFAULT: "#ffffff",
          subtle: "#f7f8fa",
          muted: "#eef0f3",
          border: "#e3e6eb",
        },
        // Secondary AI/intelligence accent — used sparingly (badges, panel
        // headers for "Intelligence" features), never as a primary CTA color.
        intel: {
          50: "#f4f1fc",
          100: "#e7e0f9",
          400: "#9d84e8",
          500: "#7c5fd6",
          600: "#6446bd",
          700: "#503697",
        },
        success: { 50: "#eafaf0", 500: "#0ca30c", 600: "#0a8a0a", 700: "#046300" },
        warning: { 50: "#fef8e9", 500: "#fab219", 600: "#a86e00", 700: "#7a5000" },
        danger: { 50: "#fdecec", 500: "#d03b3b", 600: "#b32e2e" },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(15, 33, 64, 0.04), 0 1px 3px 0 rgba(15, 33, 64, 0.06)",
        popover: "0 4px 16px -2px rgba(15, 33, 64, 0.12), 0 2px 6px -2px rgba(15, 33, 64, 0.08)",
      },
      borderRadius: {
        xl: "0.875rem",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-in-right": { from: { transform: "translateX(12px)", opacity: 0 }, to: { transform: "translateX(0)", opacity: 1 } },
        "slide-up": { from: { transform: "translateY(6px)", opacity: 0 }, to: { transform: "translateY(0)", opacity: 1 } },
      },
      animation: {
        "fade-in": "fade-in 0.15s ease-out",
        "slide-in-right": "slide-in-right 0.2s ease-out",
        "slide-up": "slide-up 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
