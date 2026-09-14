/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        app: {
          bg: "#F7F8FA",
          card: "#FFFFFF",
          border: "#EAECF0",
        },
        brand: {
          blue: "#194CFF",
          positive: "#12B76A",
          warning: "#F79009",
          critical: "#F04438",
          info: "#6172F3",
        },
        text: {
          primary: "#101828",
          secondary: "#667085",
          muted: "#98A2B3",
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      borderRadius: {
        'card': '14px',
      },
      boxShadow: {
        'subtle': '0 1px 3px 0 rgba(16, 24, 40, 0.04), 0 1px 2px 0 rgba(16, 24, 40, 0.02)',
        'card-hover': '0 4px 12px 0 rgba(16, 24, 40, 0.06)',
      }
    },
  },
  plugins: [],
}
