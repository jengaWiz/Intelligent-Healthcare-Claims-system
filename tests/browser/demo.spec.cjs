const {test, expect} = require('@playwright/test');
const path = require('path');
const sample = name => path.resolve(__dirname, `../../samples/${name}.pdf`);

async function upload(page, name) {
  await page.getByRole('button', {name: 'New document'}).click();
  await page.locator('#file').setInputFiles(sample(name));
  await page.getByRole('button', {name: 'Upload & process'}).click();
}

test('authenticated upload, correction, audit, rejection and safe failure retry', async ({page, browser}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/demo');
  await expect(page.getByRole('heading', {name: 'Welcome to Claim Studio'})).toBeVisible();
  await page.getByLabel('Demo password').fill(process.env.BROWSER_PASSWORD || 'browser-synthetic-only');
  await page.getByRole('button', {name: 'Open workspace'}).click();
  await expect(page.getByRole('heading', {name: 'Start with a synthetic document'})).toBeVisible();
  await upload(page, 'valid');
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  await expect(page.locator('#fields')).toContainText('42.50');
  await expect(page.locator('#reasoning')).toContainText('no live OCR');
  await page.screenshot({path: path.resolve(__dirname, '../../docs/screenshots/results.png'), fullPage: true});
  await upload(page, 'review');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await expect(page.locator('#issues')).toContainText('Total amount is required');
  await page.getByLabel('Review decision').selectOption('correct');
  await page.getByLabel('Billed amount (USD)').fill('48.75');
  await page.getByLabel('Reason for your decision').fill('Checked the synthetic source; recorded corrected amount.');
  await page.getByRole('button', {name: 'Save review decision'}).click();
  await expect(page.locator('#state')).toHaveText('READY');
  await expect(page.locator('#fields')).toContainText('48.75');
  await expect(page.locator('#history')).toContainText('CORRECT');
  await page.locator('#history summary').click();
  await expect(page.locator('#history pre')).toContainText('48.75');
  await page.screenshot({path: path.resolve(__dirname, '../../docs/screenshots/review.png'), fullPage: true});
  const stranger = await browser.newContext();
  const response = await stranger.request.get('/claims');
  expect(response.status()).toBe(401);
  await stranger.close();
  await upload(page, 'review');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await page.getByLabel('Review decision').selectOption('reject');
  await page.getByLabel('Reason for your decision').fill('Rejected this synthetic incomplete document.');
  await page.getByRole('button', {name: 'Save review decision'}).click();
  await expect(page.locator('#state')).toHaveText('REJECTED');
  await upload(page, 'failure');
  await expect(page.locator('#state')).toHaveText('FAILED', {timeout: 20000});
  await expect(page.getByRole('button', {name: 'Retry processing'})).toBeVisible();
  await page.getByRole('button', {name: 'Retry processing'}).click();
  await expect(page.locator('#state')).toHaveText('FAILED', {timeout: 20000});
  await page.getByRole('button', {name: 'My documents'}).click();
  await expect(page.locator('.claim-row')).toHaveCount(4);
  await page.getByRole('button', {name: 'Sign out'}).click();
  await expect(page.getByRole('heading', {name: 'Welcome to Claim Studio'})).toBeVisible();
  expect(errors).toEqual([]);
});
