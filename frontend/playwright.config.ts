import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',fullyParallel:false,workers:1,timeout:60000,
  reporter:[['list'],['html',{open:'never'}]],use:{baseURL:process.env.E2E_BASE_URL || 'http://localhost:8080',trace:'retain-on-failure',
    launchOptions:process.env.E2E_CHROME_PATH?{executablePath:process.env.E2E_CHROME_PATH}:{}},
});
