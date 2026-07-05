import { expect, APIResponse } from '@playwright/test';

export async function expectHealthyStatus(response: APIResponse, expectedStatus: number, operation: string) {
  const status = response.status();
  if ([401, 403].includes(status)) throw new Error(`[RCA:API_AUTHORIZATION] ${operation} returned ${status}. Check token, role, session, VPN/VDI or environment.`);
  if (status >= 500) throw new Error(`[RCA:API_SERVER_OR_ENVIRONMENT] ${operation} returned ${status}. Do not self-heal tests until backend/environment is checked.`);
  expect(status, `${operation}: HTTP status`).toBe(expectedStatus);
}

export async function expectJsonIfJson(response: APIResponse, operation: string) {
  const contentType = response.headers()['content-type'] || '';
  if (contentType.includes('application/json')) {
    const body = await response.json();
    expect(body, `${operation}: JSON body`).toBeTruthy();
    return body;
  }
  return null;
}
