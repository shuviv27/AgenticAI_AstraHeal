package com.aiqa.api.support;

import io.restassured.RestAssured;
import io.restassured.response.Response;
import java.util.Map;

public class EnterpriseApiClient {
  private final String baseUrl;
  public EnterpriseApiClient(String baseUrl) { this.baseUrl = baseUrl.replaceAll("/$", ""); }
  public Response call(String method, String path, Map<String, String> headers, Object body) {
    String url = path.matches("^https?://.*") ? path : baseUrl + "/" + path.replaceFirst("^/", "");
    var req = RestAssured.given().relaxedHTTPSValidation().headers(headers == null ? Map.of() : headers);
    String token = System.getenv("API_AUTH_TOKEN");
    if (token != null && !token.isBlank()) req.header("Authorization", "Bearer " + token);
    if (body != null) req.contentType("application/json").body(body);
    return switch (method.toUpperCase()) {
      case "GET" -> req.get(url);
      case "POST" -> req.post(url);
      case "PUT" -> req.put(url);
      case "PATCH" -> req.patch(url);
      case "DELETE" -> req.delete(url);
      default -> throw new IllegalArgumentException("Unsupported API method: " + method);
    };
  }
}
