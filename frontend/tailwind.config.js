/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // 品牌橘：只用在重點（主要按鈕、目前進度、需要注意的狀態）
        accent: { DEFAULT: '#C2410C', dark: '#9A3412', soft: '#FFF1E6', line: '#E8B48A' },
        // 暖灰：覆蓋 Tailwind 的 stone，全站同一個色調
        stone: {
          50: '#FAF7F2',
          75: '#FBF8F3',
          100: '#F2EEE8',
          200: '#ECE6DD',
          300: '#E2DACD',
          400: '#B5AC9F',
          500: '#6E665B',
          600: '#5C554B',
          700: '#3D362D',
          800: '#2E2820',
          900: '#221D17',
        },
      },
      fontFamily: {
        sans: ['"Noto Sans TC"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(34,29,23,.04)',
        lift: '0 10px 24px rgba(34,29,23,.10)',
        cta: '0 4px 14px rgba(194,65,12,.25)',
      },
      keyframes: {
        rise: { from: { opacity: '0', transform: 'translateY(14px)' }, to: { opacity: '1', transform: 'none' } },
        drop: { from: { opacity: '0', transform: 'translateY(-8px) scale(.98)' }, to: { opacity: '1', transform: 'none' } },
        fade: { from: { opacity: '0' }, to: { opacity: '1' } },
        ring: {
          '0%': { boxShadow: '0 0 0 0 rgba(194,65,12,.45)' },
          '70%': { boxShadow: '0 0 0 10px rgba(194,65,12,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(194,65,12,0)' },
        },
        grow: { from: { transform: 'scaleX(0)' }, to: { transform: 'scaleX(1)' } },
      },
      animation: {
        rise: 'rise .55s cubic-bezier(.2,.7,.2,1) both',
        drop: 'drop .35s cubic-bezier(.2,.7,.2,1) both',
        fade: 'fade .3s ease both',
        ring: 'ring 1.8s infinite',
        grow: 'grow .8s .4s ease-out both',
      },
    },
  },
  plugins: [],
}
