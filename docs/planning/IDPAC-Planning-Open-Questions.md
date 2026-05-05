# IDPAutoTune — Planning & Open Questions

**Status:** Active planning  
**Date:** 2026-04-08 (updated after David/Bob sync)  
**MVP Scope:** IDPAutoTune (Cost & Accuracy Optimization) only  
**Target:** NY Summit (June 2026)

---

## Decisions Made (2026-04-08)

These were agreed upon in the David/Bob sync and are no longer open questions.

1. **Autonomy level: Fully autonomous (Option A).** AutoTune will be a fully autonomous background service — no consultant in the loop, no chat interface. This is the biggest engineering challenge.
2. **Packaging: CloudFormation stack via AWS Marketplace.** Deployed in the customer's AWS account alongside their existing IDP stack. Dev starts with CDK for rapid prototyping, then converts to CFN for Marketplace distribution.
3. **Orchestration: Standalone on Agent Core.** Remove dependency on Kiro. Use Agent Core directly with standalone orchestration. Interface with the IDP stack via MCP server (not IDP CLI).
4. **Ground truth: HITL reviews count as ground truth.** Human-in-the-loop corrections feed into test set creation. Bob is working on integrating the visual editor's "use as evaluation baseline" functionality into automated test set creation.
5. **Trigger model: Scheduled (default weekly) when ground truth is updated.** Runs automatically when new ground truth data or test sets become available. Not purely time-based — tied to data availability.
6. **Repo strategy: Existing GitLab repo, separate branches.** Subscription features stay on feature branches in the GitLab repo. No merges to the public GitHub repo.
7. **UI integration: "Auto-tune" nav link in main IDP UI.** Checks subscription status — non-subscribers get redirected to AWS Marketplace. Subscribers see a unified integrated experience.
8. **CDK → CFN conversion approach:** Start with CDK, then either use CDK synthesis or wrap CDK deployment in a CodeBuild project for Marketplace-compatible CFN distribution. Exact approach TBD.

---

## Action Items

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Make auto-configure tool fully autonomous (no human intervention) | David | Not started |
| 2 | Remove Kiro dependency, implement standalone orchestration on Agent Core | David | Not started |
| 3 | Convert auto-configure to use MCP server instead of IDP CLI | David | Not started |
| 4 | Integrate HITL workflows into test set / ground truth creation | Bob | Not started |
| 5 | Research AWS Marketplace requirements and constraints | Bob | Not started |
| 6 | Set up separate Asana board for subscription services | David & Bob | Not started |
| 7 | Schedule weekly sync meetings | David & Bob | Not started |
| 8 | Investigate AWS support org for potential service support | Bob | Not started |

---

## Remaining Open Questions

### Architecture & Engineering

- **MCP server enhancements:** What specific enhancements are needed to the MCP server to support AutoTune's needs? Contractors may be engaged for this — need to identify gaps first.
- **CDK → CFN conversion:** CDK synthesis vs. CodeBuild wrapper — which approach is more maintainable? Need to prototype both and decide.
- **Permissions model:** AutoTune deploys in the customer's account and needs access to the IDP MCP server. What's the IAM permissions boundary? How do we scope this tightly?
- **State management:** Where does AutoTune store its own state? (run history, previous configs, optimization results) Separate DynamoDB table? S3?
- **Failure handling:** What happens when an optimization run fails mid-way? Partial results? Automatic retry? Rollback?

### Ground Truth & Evaluation

- **Minimum viable dataset:** How many ground truth documents are needed for a meaningful optimization run? What do we tell customers who don't have enough yet?
- **Cold start problem:** What happens before any HITL reviews have been done? Can AutoTune provide any value (e.g., cost-only optimization, model benchmarking) without ground truth?
- **Ground truth quality:** HITL reviewers can make mistakes. How do we handle noisy ground truth? Do we need a confidence threshold on the ground truth itself?
- **PII in ground truth:** Bob's HITL-to-ground-truth pipeline means real customer documents with potential PII are being used as evaluation baselines. Is this a concern given everything stays in-account?

### Approval & Config Management

- **How does the customer accept/reject recommendations?** The meeting confirmed autonomous operation, but the customer still needs to approve config changes (per the services doc). What does this approval UX look like in the "Auto-tune" UI panel?
- **Rollback:** If a customer accepts a new config and it performs worse in production than on the test set, how do they roll back?
- **Config versioning:** How do we version and store config iterations? (Tactical, but needs answering before implementation.)

### Scheduling & Triggers

- **"When ground truth is updated" detection:** How does AutoTune know new ground truth is available? S3 event notification? Polling? A signal from the HITL workflow?
- **New model releases:** The weekly schedule handles ground truth updates, but what about new Bedrock model releases? Do we also trigger on those? How do we detect them?
- **Customer override:** Can the customer manually trigger an optimization run outside the schedule? (Probably yes for MVP.)

### AWS Marketplace (Bob researching)

- What listing type fits? (SaaS subscription, metered usage, CFN template, or combination)
- How does in-account license/subscription validation work technically?
- What's the listing approval timeline? Realistic for June Summit?
- Does Marketplace support telemetry? (doc counts, optimization runs, improvement metrics)
- Pricing model options and flexibility
- End-to-end customer purchase and deployment flow
- Software update mechanism for deployed Marketplace products

### UX

- **Subscription check flow:** User clicks "Auto-tune" → checks subscription → redirects to Marketplace if not subscribed. What's the technical implementation? API call to Marketplace from the UI? Lambda-backed check?
- **Results presentation:** When AutoTune completes a run, what does the customer see? Dashboard with before/after metrics? Email notification? Both?
- **Cost/accuracy tradeoff input:** How does the customer express their preference? Slider? Presets? Or does AutoTune just present the Pareto frontier?

### Support

- **How do paying customers report problems?** Bob is investigating the AWS support org. Fallback options: dedicated portal, email, or GitHub Issues.
- **Release cadence:** How often do we push updates? Tied to Marketplace update mechanism.
- **SLA:** What response times do we commit to?

---

## Resources & Timeline

**Target:** MVP for NY Summit (June 2026)

| Person | Role | Allocation |
|--------|------|------------|
| David | Core engineering — autonomy, Agent Core, MCP, packaging | Full-time |
| Bob | HITL/ground truth integration, Marketplace research, product direction | Part-time |
| TBD (contractors) | MCP server enhancements as needed | As identified |

- Additional resources may be requested in ~3 weeks once scope is clearer.
- Beta customer candidate(s) still need to be identified.

---

## Post-MVP / Out of Scope (But Keep in Mind)

These items are explicitly out of scope for the MVP but should be considered in architectural decisions so we don't paint ourselves into a corner.

### Assessment Optimization
- Optimize assessment cost/accuracy, not just extraction
- Correlate confidence scores with actual accuracy to trigger HITL only when needed
- Factor in estimated cost of HITL review vs. cost of missed HITL reviews
- Bob flagged this as important — just not MVP

### Skills & Content Pipeline
- Collecting skills from the field
- Auto-detecting need for new skills from customer usage patterns / human review content (without exfiltrating data)
- Architecture must make this possible in the future — don't close the door

### Other Post-Production Services
- IDPModelStore, IDPMonitor, IDPCompliance, IDPReview, IDPCustomDomainAgents, IDPSupport
- AutoTune is the beachhead. These come later.

---

## Next Steps

- [x] David & Bob: Initial brainstorm meeting (2026-04-08) ✅
- [ ] Set up Asana board and weekly sync cadence
- [ ] Bob: Research Marketplace requirements (find SME, schedule deep-dive)
- [ ] Bob: Integrate HITL → ground truth pipeline
- [ ] David: Spike on removing Kiro dependency / standalone Agent Core orchestration
- [ ] David: Spike on MCP server interface (identify gaps, contractor needs)
- [ ] David: Begin CDK prototype of AutoTune stack
- [ ] Identify beta customer candidate(s)
- [ ] ~3 weeks: Reassess resource needs and request additional engineers if needed
