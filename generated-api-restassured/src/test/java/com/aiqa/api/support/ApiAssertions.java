package com.aiqa.api.support;

import io.restassured.response.Response;
import static org.junit.jupiter.api.Assertions.*;

public class ApiAssertions {
  public static void expectHealthyStatus(Response response, int expected, String operation) {
    int status = response.statusCode();
    if (status == 401 || status == 403) fail("[RCA:API_AUTHORIZATION] " + operation + " returned " + status + ". Check token, role, session, VPN/VDI or environment.");
    if (status >= 500) fail("[RCA:API_SERVER_OR_ENVIRONMENT] " + operation + " returned " + status + ". Do not self-heal tests until backend/environment is checked.");
    assertEquals(expected, status, operation + " HTTP status");
  }
}
