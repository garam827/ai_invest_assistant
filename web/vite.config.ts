import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves this repo's docs/ folder at https://garam827.github.io/ai_invest_assistant/,
// a project page (not a user/org page), so asset URLs need the repo-name base path or they'd
// resolve against the domain root and 404.
//
// Build output goes to ../docs (repo root's docs/) so this app is served from the *same*
// GitHub Pages docs/ folder that already hosts docs/reports/{date}.html and docs/data/*.json
// (see recommend.yml + static_export.py) -- no separate Pages deployment/config needed.
// emptyOutDir: false so `vite build` never deletes those directories, which it doesn't manage.
export default defineConfig({
  plugins: [react()],
  base: '/ai_invest_assistant/',
  build: {
    outDir: '../docs',
    emptyOutDir: false,
  },
})
