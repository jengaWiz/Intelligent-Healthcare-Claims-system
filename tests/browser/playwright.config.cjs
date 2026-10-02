const {defineConfig} = require('@playwright/test');
module.exports = defineConfig({testDir: '.', testMatch: '*.spec.cjs', workers: 1, retries: 0, timeout: 45000, use: {baseURL: process.env.BROWSER_BASE_URL || 'http://127.0.0.1:8047', headless: true}, reporter: [['list'], ['html', {open: 'never'}]]});
