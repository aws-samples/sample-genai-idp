# Agent SDK Selection

> Why IDPAutoTune uses Strands Agents SDK, and what else was considered.

## Decision

**Strands Agents SDK** (Apache 2.0) is the agent framework for IDPAutoTune.

The decision was made after evaluating 13 frameworks for running long-lived, headless agents on Amazon Bedrock. The primary selection criteria were: permissive licensing for a commercial product, production readiness, native Bedrock integration, first-class observability, and Python-first tooling (the existing IDPAC codebase is Python).

## Why Strands

**Production-proven at AWS scale.** Strands powers Amazon Q, Kiro, and AWS Glue internally. It reached 1.0 in July 2025.

**First-class observability.** Built-in OpenTelemetry tracing — every tool call, LLM invocation, and decision point is instrumented. Traces flow to CloudWatch or any OTEL-compatible backend. This directly supports the requirement for real-time visibility into what the autonomous agent is doing during multi-hour optimization runs.

**Native Bedrock integration.** Bedrock is the default model provider. No environment variable hacks or shelling out to external CLIs.

**Rich built-in tools.** Strands provides `file_read`, `file_write`, `editor` (smart pattern-based editing), `shell`, `python_repl`, `use_aws`, `think`, and `journal` out of the box. These cover the general-purpose file I/O, shell execution, and AWS API access that AutoTune needs, without writing custom tool wrappers.

**Clean hook system for autonomous operation.** The `AfterInvocationEvent.resume` primitive drives the optimization loop — the agent runs one iteration, then a hook decides whether to continue. `BeforeToolCallEvent` enables the cancellation mechanism (check DynamoDB status before every tool call). See [Full Autonomy Architecture](./full-autonomy.md) for details.

**Python-first.** The existing IDPAC codebase (~2,400 LOC) is Python. Strands tools are defined with a `@tool` decorator on Python functions — the IDPAC library methods map directly to tool definitions with minimal glue code.

**Apache 2.0 with no restrictive transitive dependencies.** Safe for commercial use without licensing concerns.

## Why Not Claude Agent SDK

Claude Agent SDK has an MIT license, but it **requires the Claude Code CLI** (`@anthropic-ai/claude-code`) as a runtime dependency. The Claude Code CLI is proprietary — licensed under Anthropic's Commercial Terms of Service with all rights reserved. The npm package metadata confirms this with `"SEE LICENSE IN README.md"` rather than a standard OSI license identifier.

This means the MIT license on the SDK wrapper is effectively meaningless for commercial use. The full system is governed by Anthropic's proprietary terms, making it unsuitable for building into a paid product.

This was identified as a critical blocker in the 6-week roadmap and confirmed through detailed license analysis.

## Why Not Cline SDK

Cline SDK (Apache 2.0) is a strong framework with rich built-in tools for file editing, shell execution, browser automation, and subagent spawning. However, it was not the right fit for AutoTune:

**TypeScript-first.** The IDPAC codebase is Python. Using Cline would require either shelling out from TypeScript to Python scripts (fragile), rewriting IDPAC in TypeScript (wasted effort), or wrapping Cline's CLI from a Python orchestrator (at which point there's no advantage over Strands).

**Coding-agent paradigm mismatch.** Cline is designed as a pair programmer — it excels at editing source files with smart diffs. AutoTune's agent isn't writing code; it's calling IDP APIs, analyzing evaluation metrics, and tweaking YAML configs in a structured loop. Strands' tool-calling paradigm is a better fit for this workflow.

**Observability gap.** Cline's observability is streaming JSON events over stdout. Strands provides structured OpenTelemetry traces with spans for every tool call and LLM invocation, which integrate directly into CloudWatch.

Note: Cline's hosted service Terms of Service also impose content rights requirements (irrevocable, perpetual, transferable rights to user content). Self-hosting the Apache 2.0 code avoids this, but it was an additional concern.

## Other Frameworks Evaluated

A comprehensive evaluation of 13 frameworks was conducted. Summary:

| Framework | License | Verdict |
|-----------|---------|---------|
| **Strands Agents SDK** | Apache 2.0 | ✅ Selected |
| **Claude Agent SDK** | MIT + proprietary dep | ❌ Licensing blocker |
| **Cline SDK** | Apache 2.0 | ❌ TypeScript-first, paradigm mismatch |
| **Kiro Headless** | Proprietary (AWS) | ❌ Not open source |
| **Bedrock AgentCore SDK** | Apache 2.0 | ✅ Used alongside Strands for runtime |
| **Amazon Bedrock Agents** | Proprietary (managed) | ❌ Managed service, not embeddable |
| **OpenHands** | MIT | Viable but less mature for Bedrock |
| **Goose** | Apache 2.0 (Linux Foundation) | Viable but coding-agent focused |
| **Aider** | Apache 2.0 | Scripting API unsupported, coding-focused |
| **CrewAI** | MIT | Multi-agent orchestration overkill for v1 |
| **AG2 / AutoGen** | Apache 2.0 | Multi-agent orchestration overkill for v1 |
| **LangGraph** | MIT (library) | Viable but heavier abstraction layer |
| **Spring AI AgentCore SDK** | Open source | Java — wrong language |

**Key licensing insight:** A permissive top-level license does not guarantee commercial freedom. Claude Agent SDK's MIT license is negated by its proprietary Claude Code CLI dependency. Kiro is fully proprietary. For commercial products, the cleanest options are Strands, Cline (self-hosted), AgentCore SDK, OpenHands, Goose, CrewAI, AG2, and LangGraph's core library.

## How AutoTune Uses Strands

AutoTune's agent is configured with:

- **20 domain-specific tools** wrapping IDPAC library methods (upload config, run evaluation, download results, analyze accuracy, etc.)
- **Built-in Strands tools** for general-purpose operations (file I/O, shell, Python execution, AWS API calls)
- **Two hooks** for autonomous operation:
  - `CancelCheckHook` (BeforeToolCallEvent) — reads DynamoDB cancel flag before every tool call
  - `OptimizationLoopHook` (AfterInvocationEvent) — decides whether to continue after each iteration
- **System prompt** tailored for autonomous, ground-truth-based optimization (no interactive assumptions)

The agent receives a test set ID and optional optimization guidance, then runs iteratively — analyzing results, modifying configs, re-evaluating — until it converges or hits a stopping condition. See [Full Autonomy Architecture](./full-autonomy.md) for the complete design.

## References

- [Strands Agents SDK](https://github.com/strands-agents/sdk-python) — GitHub repo
- [Strands Agents 1.0 announcement](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-1-0-production-ready-multi-agent-orchestration-made-simple)
- [Strands tools documentation](https://strandsagents.com/docs/user-guide/concepts/tools/)
- [Claude Code CLI license](https://github.com/anthropics/claude-code/blob/main/LICENSE.md) — proprietary
- [Cline SDK overview](https://docs.cline.bot/cline-sdk/overview)
- Full framework evaluation: `autotune/docs/temp-extra-doc.txt`
