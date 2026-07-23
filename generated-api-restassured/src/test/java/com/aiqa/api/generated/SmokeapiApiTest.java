package com.aiqa.api.generated;

import com.aiqa.api.support.ApiAssertions;
import com.aiqa.api.support.EnterpriseApiClient;
import io.restassured.response.Response;
import org.junit.jupiter.api.Test;
import java.util.Map;

class SmokeapiApiTest {
  private static final String BASE_URL = "http://example.com";

  @Test
  void SMOKEAPI_API_001() {
    EnterpriseApiClient client = new EnterpriseApiClient(System.getenv().getOrDefault("API_BASE_URL", BASE_URL));
    Response response = client.call("GET", "/", Map.of(), null);
    ApiAssertions.expectHealthyStatus(response, 200, "GET /");
  }

}
