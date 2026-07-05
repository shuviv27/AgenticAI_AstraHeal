package com.aiqa.api.generated;

import com.aiqa.api.support.ApiAssertions;
import com.aiqa.api.support.EnterpriseApiClient;
import io.restassured.response.Response;
import org.junit.jupiter.api.Test;
import java.util.Map;

class LoginApiTest {
  private static final String BASE_URL = "https://example.com";

  @Test
  void LOGIN_API_001() {
    EnterpriseApiClient client = new EnterpriseApiClient(System.getenv().getOrDefault("API_BASE_URL", BASE_URL));
    Response response = client.call("GET", "/", Map.of(), null);
    ApiAssertions.expectHealthyStatus(response, 200, "GET /");
  }

}
