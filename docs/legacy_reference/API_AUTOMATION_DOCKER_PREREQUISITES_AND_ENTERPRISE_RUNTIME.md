# API Automation Docker Prerequisites and Enterprise Runtime

This project supports API automation in two enterprise flavors:

1. **Playwright API tests** in TypeScript/JavaScript.
2. **Rest Assured API tests** in Java.

The recommended enterprise execution mode is **Docker runtime from GUI**. With this mode, users do not need to install Java, Maven, Node, npm, or Playwright on their host machine for API execution. The host only needs Docker Desktop running and access to the target API network/VPN.

## Why this was added

Rest Assured requires Java and Maven, while Playwright API requires Node/npm. In restricted corporate laptops and VDIs, these prerequisites are often blocked or inconsistently installed. The GUI now provides Docker-managed API runtime images and controls:

- Check API Docker prerequisites
- Pull API Docker images
- Start API mock/contract helper tools
- Execute API framework inside Docker
- RCA and self-heal failed API tests only

## Docker images used

| Purpose | Image | Notes |
|---|---|---|
| Playwright API TS/JS runtime | `mcr.microsoft.com/playwright:v1.50.0-noble` | Contains Node runtime and browser dependencies; API tests run without host Node/npm. |
| Rest Assured Java runtime | `maven:3.9-eclipse-temurin-21` | Contains Maven and Eclipse Temurin JDK 21. |
| WireMock | `wiremock/wiremock:latest` | Optional deterministic mock API server on `127.0.0.1:8089`. |
| MockServer | `mockserver/mockserver:latest` | Optional contract/mocking service on `127.0.0.1:1080`. |
| Newman | `postman/newman:alpine` | Optional Postman collection runner. |

These defaults can be overridden in `.env`:

```env
AIQA_API_PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.50.0-noble
AIQA_API_RESTASSURED_IMAGE=maven:3.9-eclipse-temurin-21
AIQA_API_NEWMAN_IMAGE=postman/newman:alpine
AIQA_API_WIREMOCK_IMAGE=wiremock/wiremock:latest
AIQA_API_MOCKSERVER_IMAGE=mockserver/mockserver:latest
```

## GUI workflow

1. Run the GUI-first startup file.
2. Open `http://127.0.0.1:8080`.
3. Open **API Automation**.
4. Click **Check API Docker Prereqs**.
5. Click **Pull API Docker Images**.
6. Optionally click **Start API Mock/Contract Tools**.
7. Keep **Run API tests inside Docker runtime** checked.
8. Generate or select an existing API framework.
9. Click **Execute API Framework**.
10. If failed, click **Analyze API RCA**.
11. Click **Propose API Fix**.
12. Click **Apply API Patch** only if policy allows.
13. Click **Re-run API Failed/Targeted**.

## What the Docker runtime solves

### Rest Assured Java

The Docker runtime provides:

- JDK
- Maven
- Maven dependency cache volume `aiqa_maven_cache`
- API environment variables
- Proxy passthrough
- Test reports under the mounted framework folder

Execution pattern:

```bash
docker run --rm -t \
  -v <api-framework>:/workspace \
  -v aiqa_maven_cache:/root/.m2 \
  -w /workspace \
  -e API_BASE_URL=<url> \
  -e API_AUTH_TOKEN=<token> \
  maven:3.9-eclipse-temurin-21 \
  bash -lc "mvn -B -ntp test"
```

### Playwright API TS/JS

The Docker runtime provides:

- Node/npm
- Playwright runtime image
- npm install inside mounted framework if `node_modules` is missing
- API environment variables
- Proxy passthrough

Execution pattern:

```bash
docker run --rm -t \
  -v <api-framework>:/workspace \
  -w /workspace \
  -e API_BASE_URL=<url> \
  -e API_AUTH_TOKEN=<token> \
  mcr.microsoft.com/playwright:v1.50.0-noble \
  bash -lc "if [ ! -d node_modules ]; then npm install; fi; npx playwright test -c playwright.api.config.ts"
```

## VDI/VPN/proxy guidance

For APIs available only through VDI/VPN:

- Start VPN before Docker Desktop if your organization requires VPN routing before Docker network creation.
- If API runs on the host laptop, use `http://host.docker.internal:<port>` from Docker containers.
- If proxy is required, set `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` in `.env` or host environment.
- Include internal domains in `NO_PROXY` when traffic should bypass proxy.
- If the VDI blocks Docker networking, run the GUI on the VDI or use local host execution as fallback.

## API RCA and self-healing policy

API failures are classified before healing:

- `API_AUTHORIZATION_OR_SESSION`
- `API_SERVER_ENVIRONMENT_OR_VPN`
- `API_ENDPOINT_OR_ROUTE_DRIFT`
- `API_SCHEMA_OR_CONTRACT_DRIFT`
- `API_ASSERTION_DRIFT_OR_PRODUCT_REGRESSION`
- `API_TEST_DATA_OR_PAYLOAD`
- `API_FRAMEWORK_COMPILATION`

The system blocks unsafe auto-healing for:

- 401/403 authorization failures
- 5xx backend failures
- schema/contract drift
- assertion drift or product behavior changes
- VPN/proxy/VDI connectivity failures

Safe patches are limited to:

- API clients
- request builders
- reusable fixtures
- endpoint mapping only when evidence proves route drift
- testData/payload only when evidence proves stale data
- generated test compilation/import fixes

## MCP and mock tools

The solution already includes Playwright MCP for browser/web assist. API automation now also adds Docker-managed mock/contract tools:

- WireMock: `http://127.0.0.1:8089`
- MockServer: `http://127.0.0.1:1080`

Use these when API tests need deterministic backend behavior, contract replay, or controlled negative testing.

## CLI equivalents

```bash
python -m qa_pipeline.cli api-docker-status
python -m qa_pipeline.cli api-docker-pull
python -m qa_pipeline.cli api-docker-start-tools
python -m qa_pipeline.cli api-framework-execute --flavor restassured --use-docker
python -m qa_pipeline.cli api-framework-execute --flavor playwright --use-docker
```

## Recommended enterprise rule

Use Docker runtime as the default for API automation. Use host runtime only when your organization has already standardized Java/Maven/Node/npm on the test machine.
