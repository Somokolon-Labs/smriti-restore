import type { Config } from "tailwindcss";

/**
 * Palette is lifted from natural dyes used in smriti kantha: indigo, madder
 * red, turmeric, terracotta, unbleached cotton.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0c0b0a",
          soft: "#141210",
          raised: "#1c1917",
          line: "#2a2522",
        },
        cotton: {
          DEFAULT: "#efe7d7",
          dim: "#b9ae9c",
          faint: "#7c7264",
        },
        indigo: {
          deep: "#16233d",
          DEFAULT: "#1d3557",
          light: "#3d5a80",
        },
        madder: "#a4243b",
        turmeric: "#d4a017",
        terracotta: "#b5643c",
        leaf: "#3f7d58",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        card: "14px",
      },
      boxShadow: {
        lift: "0 1px 0 0 rgba(239,231,215,0.06) inset, 0 18px 40px -24px rgba(0,0,0,0.9)",
        glow: "0 0 0 1px rgba(212,160,23,0.35), 0 0 32px -8px rgba(212,160,23,0.25)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "stitch-spin": {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.45s cubic-bezier(0.22,1,0.36,1) both",
        shimmer: "shimmer 1.8s infinite",
        "stitch-spin": "stitch-spin 1.1s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
