import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    // The UI renders local time, so tests must not run in the host timezone.
    // Asia/Kolkata is a fixed +05:30 offset with no daylight saving transition.
    env: { TZ: 'Asia/Kolkata' },
  },
});
