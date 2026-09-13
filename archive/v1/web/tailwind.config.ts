import type { Config } from "tailwindcss";

/**
 * FleetBeat brand tokens (Section 1 of the product spec).
 *
 * `coral` is the Alert Coral accent and is reserved for live/critical
 * indicators only - alerts, danger states and the heartbeat pulse. It is
 * never a primary UI colour.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        electric: {
          DEFAULT: "#1E90FF",
          50: "#EAF4FF",
          100: "#D3E8FF",
          200: "#A7D1FF",
          300: "#7ABAFF",
          400: "#4EA3FF",
          500: "#1E90FF",
          600: "#0B72D6",
          700: "#0857A3",
          800: "#063D73",
          900: "#042543",
        },
        coral: {
          DEFAULT: "#FF6B35",
          500: "#FF6B35",
          600: "#E85520",
        },
        ink: {
          DEFAULT: "#121417",
          900: "#121417",
          800: "#181B20",
          700: "#20242B",
          600: "#2A2F38",
          500: "#3A404B",
          400: "#5B6371",
          300: "#8A93A3",
          200: "#B9C0CC",
          100: "#E1E5EC",
          50: "#F5F7FA",
        },
        success: "#2ECC71",
        warning: "#F5A623",
        danger: "#E74C3C",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        // The "Beat" in FleetBeat: used for live-status dots and loaders.
        heartbeat: {
          "0%, 100%": { transform: "scale(1)", opacity: "1" },
          "50%": { transform: "scale(1.35)", opacity: "0.65" },
        },
        pulsering: {
          "0%": { transform: "scale(0.8)", opacity: "0.7" },
          "100%": { transform: "scale(2.4)", opacity: "0" },
        },
      },
      animation: {
        heartbeat: "heartbeat 1.6s ease-in-out infinite",
        pulsering: "pulsering 1.8s ease-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
