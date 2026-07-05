import { test } from '@playwright/test';
import { EnterpriseApiClient } from '../../utils/apiClient';
import { expectHealthyStatus, expectJsonIfJson } from '../../utils/apiAssertions';
import scenarios from '../../testData/login.api.scenarios.json';

test.describe('login API generated suite', () => {
  for (const scenario of scenarios.scenarios) {
    test(`${scenario.id} - ${scenario.title}`, async ({ request }, testInfo) => {
      const baseUrl = process.env.API_BASE_URL || scenarios.base_url || 'https://example.com';
      const client = new EnterpriseApiClient(request, baseUrl);
      const response = await client.call(scenario.method, scenario.path, { headers: scenario.headers || {}, data: scenario.body || undefined });
      await client.attachEvidence(testInfo, response, scenario.id);
      await expectHealthyStatus(response, scenario.expected_status, `${scenario.method} ${scenario.path}`);
      await expectJsonIfJson(response, `${scenario.method} ${scenario.path}`);
    });
  }
});
