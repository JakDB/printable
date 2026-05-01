/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        serif: ['Playfair Display', 'Georgia', 'serif']
      },
      colors: {
        background: '#f8f7f5',
        foreground: '#262626',
        card: '#ffffff',
        'card-foreground': '#262626',
        primary: '#262626',
        'primary-foreground': '#f8f7f5',
        secondary: '#f2f1ef',
        'secondary-foreground': '#262626',
        muted: '#ebebe8',
        'muted-foreground': '#737373',
        accent: '#d4795a',
        'accent-foreground': '#ffffff',
        border: '#ebebe8',
        ring: '#262626',
        'rgb-red': '#df5a4c',
        'rgb-green': '#6cb869',
        'rgb-blue': '#5078c8',
        'cmyk-cyan': '#62c7d9',
        'cmyk-magenta': '#c94f9b',
        'cmyk-yellow': '#f0d15c',
        'cmyk-black': '#404040'
      },
      borderRadius: {
        sm: '0.375rem',
        md: '0.5rem',
        lg: '0.75rem',
        xl: '1rem'
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' }
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' }
        }
      },
      animation: {
        'fade-in': 'fade-in 0.5s ease-out forwards',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite'
      }
    }
  },
  plugins: []
}
