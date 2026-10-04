const {test, expect} = require('@playwright/test');
const path = require('path');
test.use({viewport: {width: 1440, height: 1000}});

const sample = name => path.resolve(__dirname, `../../samples/${name}.pdf`);

async function screenshotWorkspace(page, name) {
  await page.evaluate(() => window.scrollTo(0, 0));
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({width: 1440, height: Math.min(height, 1600)});
  await page.screenshot({path: path.resolve(__dirname, `../../docs/screenshots/${name}.png`), fullPage: false});
  await page.setViewportSize({width: 1440, height: 1000});
}

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
  await expect(page.getByRole('heading', {name: 'New claim', exact: true})).toBeVisible();
  await upload(page, 'valid');
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('LOW');
  await screenshotWorkspace(page, 'results');
  await page.getByLabel('Reason for risk acknowledgment').fill('Checked the synthetic evidence.');
  await page.getByRole('button', {name: 'Record risk acknowledgment'}).click();
  await expect(page.locator('#risk-acknowledgment')).toContainText('Computed risk is unchanged');
  await page.getByRole('button', {name: 'Refresh risk assessment', exact: true}).click();
  await expect(page.locator('#risk-level')).toHaveText('LOW');
  await expect(page.locator('#fields')).toContainText('42.50');
  await expect(page.locator('#reasoning')).toContainText('no live OCR');
  await upload(page, 'review');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('INSUFFICIENT DATA');
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
  await page.locator('#history summary').click();
  await screenshotWorkspace(page, 'review');
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
  await page.getByRole('button', {name: 'Risk queue', exact: false}).click();
  await expect(page.locator('.claim-row')).toHaveCount(1);
  await expect(page.locator('.claim-row')).toContainText('LOW');
  await page.getByLabel('Risk acknowledgment filter').selectOption('all');
  await expect(page.locator('.claim-row')).toHaveCount(2);
  await page.getByRole('button', {name: 'New document'}).click();
  await page.getByRole('button', {name: 'My documents'}).click();
  await page.locator('.claim-row').filter({hasText: 'FAILED'}).getByRole('button', {name: 'Open'}).click();
  await expect(page.getByRole('button', {name: 'Retry processing'})).toBeVisible();
  let releaseRetry;
  const retryGate = new Promise(resolve => { releaseRetry = resolve; });
  await page.route('**/documents/*/extract', async route => {
    await retryGate;
    await route.continue();
  });
  await page.getByRole('button', {name: 'Retry processing'}).click();
  await expect(page.getByRole('button', {name: 'Sign out'})).toBeDisabled();
  releaseRetry();
  await expect(page.getByRole('button', {name: 'Sign out'})).toBeEnabled();
  await page.unroute('**/documents/*/extract');
  await expect(page.locator('#state')).toHaveText('FAILED', {timeout: 20000});
  await page.getByRole('button', {name: 'My documents'}).click();
  await expect(page.locator('.claim-row')).toHaveCount(4);
  await page.getByRole('button', {name: 'Sign out'}).click();
  await expect(page.getByRole('heading', {name: 'Welcome to Claim Studio'})).toBeVisible();
  expect(errors).toEqual([]);
});

test('versioned risk corpus, exact duplicates and snapshot refresh', async ({page}) => {
  await page.goto('/demo');
  await page.getByLabel('Demo password').fill(process.env.BROWSER_PASSWORD || 'browser-synthetic-only');
  await page.getByRole('button', {name: 'Open workspace'}).click();
  await upload(page, 'valid');
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('LOW');
  const firstId = (await page.locator('#claim-reference').textContent()).match(/[0-9a-f-]{36}/)[0];
  await upload(page, 'valid');
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await expect(page.locator('#risk-signals')).toContainText('identical bytes');
  const original = await (await page.request.get(`/claims/${firstId}/results`)).json();
  expect(original.risk.level).toBe('LOW');
  const session = await (await page.request.get('/auth/session')).json();
  const refreshed = await page.request.post(`/claims/${firstId}/risk/refresh`, {
    headers: {Origin: process.env.BROWSER_BASE_URL || 'http://127.0.0.1:8047', 'X-CSRF-Token': session.csrf_token},
    data: {expected_version: original.claim.version},
  });
  expect(refreshed.status()).toBe(200);
  expect((await refreshed.json()).level).toBe('HIGH');
  await upload(page, 'medium');
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('MEDIUM');
  await upload(page, 'high');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await screenshotWorkspace(page, 'risk');
  await upload(page, 'review');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await expect(page.locator('#risk-level')).toHaveText('INSUFFICIENT DATA');
  await page.getByRole('button', {name: 'Risk queue', exact: false}).click();
  await expect(page.locator('.claim-row')).toHaveCount(5);
  expect(await page.locator('.claim-row .badge').allTextContents()).toEqual(['HIGH','HIGH','HIGH','MEDIUM','INSUFFICIENT DATA']);
});

test('risk explanations, HIGH acknowledgment, history and stale conflict recovery', async ({page}) => {
  await page.goto('/demo');
  await page.getByLabel('Demo password').fill(process.env.BROWSER_PASSWORD || 'browser-synthetic-only');
  await page.getByRole('button', {name: 'Open workspace'}).click();
  await upload(page, 'review');
  await expect(page.locator('#state')).toHaveText('REVIEW REQUIRED', {timeout: 20000});
  await page.getByLabel('Review decision').selectOption('correct');
  await page.getByLabel('Billed amount (USD)').fill('100001');
  await page.getByLabel('Reason for your decision').fill('Confirmed synthetic amount.');
  await page.getByRole('button', {name: 'Save review decision'}).click();
  await expect(page.locator('#state')).toHaveText('READY');
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await expect(page.locator('#risk-signals')).toContainText('illustrative high review threshold');
  await page.getByRole('button', {name: 'Show assessment history'}).click();
  await expect(page.locator('#risk-history details')).toHaveCount(2);
  await page.route('**/risk/acknowledgments', route => route.fulfill({status: 409, contentType: 'application/json', body: JSON.stringify({code:'stale_assessment',message:'Refresh the current risk assessment'})}));
  await page.getByLabel('Reason for risk acknowledgment').fill('Investigated synthetic rule.');
  await page.getByRole('button', {name: 'Record risk acknowledgment'}).click();
  await expect(page.locator('#message')).toContainText('stale_assessment');
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await page.unroute('**/risk/acknowledgments');
  await page.getByRole('button', {name: 'Record risk acknowledgment'}).click();
  await expect(page.locator('#risk-acknowledgment')).toContainText('Computed risk is unchanged');
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await page.getByRole('button', {name: 'Risk queue', exact: false}).click();
  await expect(page.locator('.claim-row')).toHaveCount(0);
  await page.getByLabel('Risk acknowledgment filter').selectOption('all');
  await expect(page.locator('.claim-row')).toHaveCount(1);
  await page.getByLabel('Risk level filter').selectOption('LOW');
  await expect(page.locator('.claim-row')).toHaveCount(0);
  await page.getByLabel('Risk level filter').selectOption('HIGH');
  await expect(page.locator('.claim-row')).toHaveCount(1);
});


test('mobile reviewer can investigate, acknowledge and approve without horizontal overflow', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/demo');
  await page.getByLabel('Demo password').fill(process.env.BROWSER_PASSWORD || 'browser-synthetic-only');
  await page.getByRole('button', {name: 'Open workspace'}).click();
  await page.getByRole('button', {name: 'Use high risk sample', exact: true}).click();
  await expect(page.locator('#risk-level')).toHaveText('HIGH', {timeout: 20000});
  await expect(page.locator('#fields')).toContainText('$100,001.00');
  await expect(page.locator('#source-file')).toHaveText('high.pdf');
  await expect(page.locator('#record-patient')).toHaveText('Synthetic Example');
  await page.getByRole('link', {name: 'Review document'}).click();
  await expect(page.locator('#review-panel')).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel('Reason for risk acknowledgment').fill('Investigated synthetic high amount on mobile.');
  await page.getByRole('button', {name: 'Record risk acknowledgment'}).click();
  await expect(page.locator('#risk-acknowledgment')).toContainText('Computed risk is unchanged');
  await page.getByLabel('Reason for your decision').fill('Verified the synthetic document data.');
  await page.getByRole('button', {name: 'Save review decision'}).click();
  await expect(page.locator('#state')).toHaveText('READY');
  await expect(page.locator('#risk-level')).toHaveText('HIGH');
  await page.getByRole('button', {name: 'Risk queue', exact: true}).click();
  await expect(page.locator('.claim-row')).toHaveCount(1);
  await expect(page.getByRole('button', {name: 'Risk queue', exact: true})).toHaveAttribute('aria-current', 'page');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.claim-row').getByRole('button', {name: 'Open'}).click();
  await page.getByText('Policy & assessment details', {exact: true}).click();
  await expect(page.locator('#risk-meta')).toBeVisible();
  await page.getByRole('button', {name: 'Sign out'}).click();
  await expect(page.getByRole('heading', {name: 'Welcome to Claim Studio'})).toBeVisible();
});

test('switching cases ignores delayed document metadata from the previous selection', async ({page}) => {
  await page.goto('/demo');
  await page.getByLabel('Demo password').fill(process.env.BROWSER_PASSWORD || 'browser-synthetic-only');
  await page.getByRole('button', {name: 'Open workspace'}).click();
  await page.getByRole('button', {name: 'Use complete claim sample', exact: true}).click();
  await expect(page.locator('#state')).toHaveText('READY', {timeout: 20000});
  const firstId = (await page.locator('#claim-reference').textContent()).match(/[0-9a-f-]{36}/)[0];
  const first = await (await page.request.get(`/claims/${firstId}/results`)).json();
  await page.getByRole('button', {name: 'New document'}).click();
  await page.getByRole('button', {name: 'Use medium risk sample', exact: true}).click();
  await expect(page.locator('#risk-level')).toHaveText('MEDIUM', {timeout: 20000});
  const secondId = (await page.locator('#claim-reference').textContent()).match(/[0-9a-f-]{36}/)[0];
  let releaseMetadata, metadataStarted;
  const gate = new Promise(resolve => { releaseMetadata = resolve; });
  const started = new Promise(resolve => { metadataStarted = resolve; });
  const sourceURL = `**/documents/${first.job.document_id}`;
  await page.route(sourceURL, async route => {
    metadataStarted();
    await gate;
    await route.continue();
  });
  await page.getByRole('button', {name: 'My documents'}).click();
  await page.locator('.claim-row').filter({hasText: firstId}).getByRole('button', {name: 'Open'}).click();
  await started;
  await page.getByRole('button', {name: 'My documents'}).click();
  await page.locator('.claim-row').filter({hasText: secondId}).getByRole('button', {name: 'Open'}).click();
  await expect(page.locator('#source-file')).toHaveText('medium.pdf');
  const delayedResponse = page.waitForResponse(response => response.url().endsWith(`/documents/${first.job.document_id}`));
  releaseMetadata();
  await delayedResponse;
  await expect(page.locator('#claim-reference')).toContainText(secondId);
  await expect(page.locator('#source-file')).toHaveText('medium.pdf');
  await expect(page.locator('#record-total')).toHaveText('$10,001.00');
});
