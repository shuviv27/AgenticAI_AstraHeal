# Auditable Existing-Framework RCA Chain

This file records evidence-based RCA decisions. It is intentionally an auditable summary, not hidden model chain-of-thought.

- Generated: `2026-07-16T02:16:25`
- Framework: `C:\PROJECTS\qa_acima_testautomation_execution_fixed\qa_acima_fixed`
- Failed specs: `tests/mobile/mobile-home.spec.ts, tests/ui/dashboard.spec.ts`

## Selected decision
```json
{
  "step": "Chain 2 - Trace timing classifier",
  "decision": "Trace/failure text indicates action fired too early/late or target not actionable.",
  "confidence": 0.8,
  "evidence_keys": [
    "playwright_trace_replay",
    "failure_text"
  ],
  "auto_patch_candidate": true,
  "healing_strategy": "Patch reusable waits, waitForStableDom, safeClick, overlay dismissal, and navigation expectations."
}
```

## Chain matrix
| Chain | Decision | Confidence | Auto patch? | Strategy |
|---|---|---|---|---|
| Chain 2 - Trace timing classifier | Trace/failure text indicates action fired too early/late or target not actionable. | 0.8 | Yes | Patch reusable waits, waitForStableDom, safeClick, overlay dismissal, and navigation expectations. |

## Evidence index
```json
{
  "failure_run_dirs": [],
  "trace_files": [
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-04/html/data/c1e7053815dc2f6d63653c2001a792102764676a.zip",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-04/test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium-retry1/trace.zip",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-02/html/data/079d75526e317f2633fb4ff601c53947d3813eb6.zip",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-02/test-results/mobile-mobile-home-Mobile--2b884-tton-visible-and-functional-chromium-retry1/trace.zip",
    "reports/existing-framework/html/data/a2886c4046c57c87d50cef77b7811e2fde5fcb5d.zip",
    "test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium-retry1/trace.zip"
  ],
  "har_files": [],
  "dom_snapshot_files": [],
  "screenshots": [
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-04/html/data/9e017539a3aab1d055ab50acbac88231dad9ceef.png",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-04/test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium-retry1/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-04/test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-02/html/data/710c8e689136706d134305b94712f31335baeeaa.png",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-02/test-results/mobile-mobile-home-Mobile--2b884-tton-visible-and-functional-chromium-retry1/test-failed-1.png",
    "reports/existing-framework/distributed-runs/run-20260716-015622/shard-02/test-results/mobile-mobile-home-Mobile--2b884-tton-visible-and-functional-chromium/test-failed-1.png",
    "reports/existing-framework/html/data/9e017539a3aab1d055ab50acbac88231dad9ceef.png",
    "test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium-retry1/test-failed-1.png",
    "test-results/ui-dashboard-Dashboard-–-C-e9212-s-sold-lease-status-message-chromium/test-failed-1.png"
  ]
}
```
