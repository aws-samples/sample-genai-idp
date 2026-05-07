# Circuit Breaker Manager

Protects the system from cascading failures when Bedrock services are degraded or unavailable.

## State Diagram

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
              ┌──────────┐                                    │
              │  CLOSED  │◄───────────────────────────────────┤
              │ (normal) │         Alarm OK + probe succeeds  │
              └────┬─────┘                                    │
                   │                                          │
                   │ CloudWatch Alarm                         │
                   │ (Bedrock errors)                         │
                   ▼                                          │
              ┌──────────┐                                    │
              │   OPEN   │ ◄──── Alarm during HALF_OPEN       │
              │ (reject) │                                    │
              └────┬─────┘                                    │
                   │                                          │
                   │ Recovery timeout expires                 │
                   │ OR Alarm returns to OK                   │
                   ▼                                          │
              ┌───────────┐                                   │
              │ HALF_OPEN │───────────────────────────────────┘
              │  (probe)  │
              └───────────┘
```

## How It Works

```
┌─────────────┐    SNS     ┌────────────────────┐    DynamoDB    ┌──────────────┐
│ CloudWatch  │───────────►│  Circuit Breaker   │◄──────────────►│ Concurrency  │
│   Alarm     │            │     Manager        │                │    Table     │
└─────────────┘            └────────────────────┘                └──────────────┘
                                   │                                    ▲
                                   │ SNS                                │
                                   ▼                                    │
                           ┌──────────────┐                             │
                           │ AlertsTopic  │                             │
                           │ (notify ops) │                             │
                           └──────────────┘                             │
                                                                        │
┌─────────────┐                                                         │
│    SQS      │────────────►┌─────────────────┐  check state before     │
│   Queue     │             │ Queue Processor │─────processing──────────┘
└─────────────┘             └─────────────────┘
                                   │
                                   │ if CLOSED or HALF_OPEN
                                   ▼
                           ┌─────────────────┐
                           │  Step Functions │
                           │    Workflow     │
                           └─────────────────┘
```

## States

| State | Behavior |
|-------|----------|
| **CLOSED** | Normal operation. All requests processed. |
| **OPEN** | Bedrock unavailable. Messages return to SQS for retry. |
| **HALF_OPEN** | Testing recovery. Limited traffic allowed through. |

## Triggers

- **CLOSED → OPEN**: CloudWatch Alarm fires (Bedrock throttling/errors)
- **OPEN → HALF_OPEN**: Recovery timeout expires (default 5 min) or alarm clears
- **HALF_OPEN → CLOSED**: Probe traffic succeeds, alarm stays OK
- **HALF_OPEN → OPEN**: New alarm during recovery testing

## Alarm Threshold

The `BedrockServiceOutageAlarm` uses MetricMath to sum the Bedrock error categories you opt in to, and compares the total to `CircuitBreakerFailureThreshold`.

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `CircuitBreakerEnabled` | false | true/false | Master switch. Set to `true` to provision the alarm, SNS topic, manager Lambda, and traffic gate. |
| `CircuitBreakerTriggerServiceUnavailable` | true | true/false | Count `BedrockServiceUnavailable` (503) toward threshold |
| `CircuitBreakerTriggerThrottling` | false | true/false | Count `BedrockThrottling` (ThrottlingException, TooManyRequestsException, RequestLimitExceeded) toward threshold |
| `CircuitBreakerTriggerQuotaLimit` | false | true/false | Count `BedrockQuotaLimit` (ServiceQuotaExceededException) toward threshold |
| `CircuitBreakerFailureThreshold` | 3 | 1-100 | Combined error count per period to breach |
| `CircuitBreakerEvaluationPeriods` | 1 | 1-10 | Consecutive 5-min periods that must breach |

**Default behavior**: The circuit breaker is **disabled by default** (`CircuitBreakerEnabled=false`). When enabled, **3+ ServiceUnavailable errors in a single 5-minute window** opens the circuit breaker. Throttling and quota-limit errors are not counted by default, since those indicate client-side load issues rather than a Bedrock outage.

Enable additional triggers when you want the breaker to also protect against sustained throttling or quota exhaustion. The metrics are summed, so a threshold of 3 with both ServiceUnavailable and Throttling enabled opens the breaker on any combination totaling 3 errors in the window.

These are CloudFormation stack parameters configurable at deployment time.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RECOVERY_TIMEOUT_SECONDS` | 300 | Seconds before OPEN → HALF_OPEN |
| `ERROR_HANDLER_ARN` | (none) | Optional Lambda for custom handling |
| `METRIC_NAMESPACE` | GENAIDP | CloudWatch metrics namespace |

## Manual Operations

Reset the circuit breaker:
```bash
aws lambda invoke --function-name <CircuitBreakerManager> \
  --payload '{"action": "reset"}' response.json
```

Check current state:
```bash
aws lambda invoke --function-name <CircuitBreakerManager> \
  --payload '{"action": "get_state"}' response.json
```
