# Auditable Existing-Framework RCA Chain

This file records evidence-based RCA decisions. It is intentionally an auditable summary, not hidden model chain-of-thought.

- Generated: `2026-07-06T01:41:13`
- Framework: `C:\PROJECTS\qa_acima_testautomation_execution_fixed\qa_acima_fixed`
- Failed specs: `tests/ui/login.spec.ts, tests/ui/static-pages.spec.ts`

## Selected decision
```json
{
  "step": "Chain 5 - Assertion drift classifier",
  "decision": "Assertion value drift is below semantic threshold or behavioral; human review required.",
  "confidence": 0.9,
  "evidence_keys": [
    "assertion_drift_classifier"
  ],
  "auto_patch_candidate": false,
  "healing_strategy": "Do not auto-update assertion. Create PR comment with expected/received and similarity score."
}
```

## Chain matrix
| Chain | Decision | Confidence | Auto patch? | Strategy |
|---|---|---|---|---|
| Chain 5 - Assertion drift classifier | Assertion value drift is below semantic threshold or behavioral; human review required. | 0.9 | No | Do not auto-update assertion. Create PR comment with expected/received and similarity score. |
| Chain 2 - Trace timing classifier | Trace/failure text indicates action fired too early/late or target not actionable. | 0.89 | Yes | Patch reusable waits, waitForStableDom, safeClick, overlay dismissal, and navigation expectations. |

## Evidence index
```json
{
  "failure_run_dirs": [],
  "trace_files": [
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/html/data/7a7e0223a556539af298cd3d9b79275143cc6382.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/html/data/52927aa80a6cda87328bccec3f91cadff688646c.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/test-results/ui-login-Login-–-Customer-Portal-Logout-clears-session-chromium-retry1/trace.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/006608cb8e60b2c73255cf0ca4ebbdc28e5873af.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/388a0f889fd61f69da3ba658a3b8cd813b13b636.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-84877--–-Mobile-App-section-valid-chromium-retry1/trace.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-21a2b-–-Main-Banner-section-valid-chromium-retry1/trace.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium-retry1/trace.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-01/html/data/ad134e1699e55a344de6b4214ce294d5dd115db3.zip",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-01/test-results/mobile-mobile-home-Mobile--2b884-tton-visible-and-functional-chromium-retry1/trace.zip"
  ],
  "har_files": [],
  "dom_snapshot_files": [],
  "screenshots": [
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/html/data/b319b08498687dd5c2798ee993922b1d1bc726ae.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/html/data/794d017e4da8031bb5fe10053facf33efdb8a79d.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/test-results/ui-login-Login-–-Customer-Portal-Logout-clears-session-chromium-retry1/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/test-results/ui-login-Login-–-Customer-Portal-Logout-clears-session-chromium/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/0eee792b1fd55f500a6b9dc34f5b13382b244148.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/d8c73244dfe4e998c422ae2f9d1703b57647e3f6.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/83432cd94df6300b3136b074e4182e369e35c767.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/html/data/674f45a11908d7e72e376ec84263278725fc6e13.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-84877--–-Mobile-App-section-valid-chromium-retry1/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-84877--–-Mobile-App-section-valid-chromium/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-21a2b-–-Main-Banner-section-valid-chromium-retry1/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-05/test-results/ui-static-pages-Static-Pag-21a2b-–-Main-Banner-section-valid-chromium/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-01/html/data/7785fa0a79ddde3e34057c858dcff544e760e76d.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-04/test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260706-011339/shard-01/test-results/mobile-mobile-home-Mobile--2b884-tton-visible-and-functional-chromium/test-failed-1.png"
  ]
}
```
