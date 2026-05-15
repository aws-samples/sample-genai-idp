# Phase E — Test harness

End-to-end coverage of the 7-state FeaturePage machine, exercised through the
real Phase A Lambdas against moto-mocked AWS services.

## What's here

```
test-harness/
├── README.md                    (this file)
├── conftest.py                  Shared fixtures (moto + Lambda loaders)
├── test_seven_state_machine.py  Transitions through all 7 UI states
├── test_install_uninstall_flow.py   Full Create/Delete of a feature row
└── mini-main-stack.yaml         Minimal CFN to spin up Phase A in a sandbox
```

## Matrix covered

| # | Transition                                    | Test method |
|---|-----------------------------------------------|-------------|
| 1 | no entitlement → SubscriptionRequired         | `test_state_none_returns_subscription_required` |
| 2 | ACTIVE + not installed + admin → InstallPrompt | `test_state_active_admin_not_installed` |
| 3 | ACTIVE + not installed + non-admin → AwaitingAdminInstall | `test_state_active_nonadmin_not_installed` |
| 4 | ACTIVE + installed at latest → UpToDate       | `test_state_active_installed_up_to_date` |
| 5 | ACTIVE + installed with newer latest → UpdateAvailable | `test_state_active_installed_update_available` |
| 6 | UpdateAvailable + admin triggers launch → stackName preserved | `test_update_preserves_stack_name` |
| 7 | EXPIRED + installed → ExpiredBanner           | `test_state_expired_installed` |

Plus install/unregister flow:
- `test_full_install_flow_register_then_list`
- `test_unregister_removes_from_list`
- `test_upgrade_overwrites_installed_version`

## Run

```bash
cd subscription-features/feature-platform/test-harness
python -m pytest -v
```

The tests import the Phase A Lambda handlers directly from
`subscription-features/feature-platform/main-stack-extensions/lambdas/`, so no deployment
is required — pure unit + state-machine coverage.

## `mini-main-stack.yaml`

This is the minimal CFN template for wiring the Phase A pieces into a real AWS
account when you want a live integration test (outside of unit tests). It
creates:

- A dummy AppSync API (`AWS::AppSync::GraphQLApi`)
- A dummy Cognito User Pool + Client
- A dummy `WebUIBucket`
- The Phase A nested stack from `../main-stack-extensions/cfn/feature-platform.yaml`

Intended for `sam deploy` in a sandbox account to validate the seller-bucket
→ feature-stack install path without spinning up the full IDP accelerator.
