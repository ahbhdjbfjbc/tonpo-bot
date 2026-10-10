tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: { 900: '#0a0e17', 800: '#0f1520', 700: '#151c2c', 600: '#1c2538', 500: '#243044' },
        accent: { DEFAULT: '#3b82f6', soft: '#1d4ed8', glow: '#60a5fa' },
        profit: '#22c55e', loss: '#ef4444', warn: '#f59e0b',
      },
      fontFamily: {
        sans: ['IBM Plex Sans Arabic', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    }
  }
};
