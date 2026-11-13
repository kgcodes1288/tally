import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The built app is served by the Tally API (same origin). In dev, /api is proxied to it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true, proxy: { '/api': process.env.TALLY_API ?? 'http://127.0.0.1:8300' } },
})
