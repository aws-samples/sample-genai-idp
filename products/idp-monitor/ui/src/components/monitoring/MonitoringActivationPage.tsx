// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Activation Page
 *
 * Shown when the customer navigates to /monitoring but has not deployed
 * the IDPMonitor stack. Explains what IDPMonitor is, how to activate it,
 * and links to documentation / deployment instructions.
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import SpaceBetween from '@cloudscape-design/components/space-between';

const FEATURES = [
  {
    title: 'Document Volume & Throughput',
    description:
      'Track processed document counts, success rates, and throughput over any time window.',
  },
  {
    title: 'Cost & Token Analytics',
    description:
      'Monitor Bedrock token usage and estimated inference costs per model, broken down by time.',
  },
  {
    title: 'Pipeline Latency (X-Ray)',
    description:
      'View P50/P90/P99 latency percentiles end-to-end and per pipeline stage.',
  },
  {
    title: 'Failure Investigation',
    description:
      'Browse recent processing failures and deep-link into the Error Analyzer for root-cause analysis.',
  },
  {
    title: 'Throttle & Performance',
    description:
      'Spot Lambda, Bedrock, and Textract throttle events with severity-based alerting.',
  },
  {
    title: 'Configuration Context',
    description:
      'Correlate processing changes with config deployments using version history.',
  },
];

export function MonitoringActivationPage(): JSX.Element {
  return (
    <Box padding={{ top: 'xxxl', bottom: 'xxxl' }}>
      <Box textAlign="center" margin={{ bottom: 'xxl' }}>
        <SpaceBetween size="m" direction="vertical">
          <Box fontSize="display-l" fontWeight="bold" color="text-label">
            📊
          </Box>
          <Box variant="h1">Activate IDPMonitor</Box>
          <Box variant="p" color="text-body-secondary" fontSize="body-s">
            IDPMonitor gives you real-time visibility into your IDP Accelerator
            pipeline — processing volume, costs, latency, failures, and more.
          </Box>
          <SpaceBetween size="s" direction="horizontal">
            <Button
              variant="primary"
              href="https://docs.aws.amazon.com/idp-accelerator/monitoring/deploy"
              target="_blank"
              iconAlign="right"
              iconName="external"
            >
              Deploy IDPMonitor
            </Button>
            <Button
              variant="normal"
              href="https://aws.amazon.com/idp-accelerator/monitoring"
              target="_blank"
              iconAlign="right"
              iconName="external"
            >
              Learn More
            </Button>
          </SpaceBetween>
        </SpaceBetween>
      </Box>

      <Container
        header={
          <Header variant="h2">What you get with IDPMonitor</Header>
        }
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '16px',
          }}
        >
          {FEATURES.map((f) => (
            <Box
              key={f.title}
              padding="l"
            >
              <SpaceBetween size="xs">
                <Box variant="h3" fontWeight="bold">
                  {f.title}
                </Box>
                <Box variant="p" color="text-body-secondary">
                  {f.description}
                </Box>
              </SpaceBetween>
            </Box>
          ))}
        </div>
      </Container>

      <Box textAlign="center" margin={{ top: 'xl' }}>
        <Box variant="p" color="text-body-secondary">
          Need help getting started?{' '}
          <Link
            href="https://docs.aws.amazon.com/idp-accelerator/monitoring"
            target="_blank"
            external
          >
            View the documentation
          </Link>
        </Box>
      </Box>
    </Box>
  );
}
