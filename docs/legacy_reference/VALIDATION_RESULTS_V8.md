# Validation Results — V8 Dynamic Web Build

Validated in sandbox:

```text
python -m compileall -q qa_pipeline
python -m qa_pipeline.cli generate-testcases --source samples/srs/acima_requirements.txt --source-type srs --feature acima --base-url https://www.acima.com/en
python -m qa_pipeline.cli run-e2e --source samples/srs/acima_requirements.txt --source-type srs --feature acima --base-url https://www.acima.com/en --provider deterministic --skip-npm
cd generated-playwright && npm install && npm run build
```

Result:

```text
Python compile: PASS
Functional testcase generation: PASS
Reuse-aware Playwright generation: PASS
No inline locators in generated spec: PASS
TypeScript build: PASS after npm install
Docker runtime: not executed in sandbox; run locally with scripts/START_DOCKER_AND_AI_*.sh|ps1
Codex/Ollama provider runtime: not executed in sandbox; check locally after login/model setup
Live website execution: not executed in sandbox; run locally/VDI after verifying site access
```
