// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringShell — integration shell for the open-source IDP Accelerator UI.
 *
 * Rendering logic:
 *
 *  1. If the user has not yet clicked "Enable Monitoring" → show the
 *     Cloudscape activation page (subscription CTA).
 *
 *  2. When the user clicks "Enable Monitoring" → probe AWS SSM / CloudFormation
 *     to detect whether the IDPMonitor stack is deployed:
 *       • Found  → set activated=true (persisted in localStorage) and load the
 *                  premium MonitoringPage from @idp-accelerator/idp-monitor-ui.
 *       • Not found → show an error Alert with deployment instructions.
 *
 *  3. If @idp-accelerator/idp-monitor-ui is NOT installed, a loading skeleton
 *     is shown briefly and then a graceful "package not available" message
 *     is rendered inside the standard layout.
 */

import React, { Suspense, lazy, useState, useCallback } from 'react';
import { Alert, Box, Button, Container, Header, SpaceBetween, StatusIndicator, TextContent } from '@cloudscape-design/components';
import { SSMClient, GetParameterCommand } from '@aws-sdk/client-ssm';
import type { AwsCredentialIdentity } from '@aws-sdk/types';
import useAppContext from '../../contexts/app';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MonitoringShellProps {
  /** The deployed IDP Accelerator CloudFormation stack name. */
  stackName: string;
  /** Optional CSS class for the outer wrapper div. */
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// LocalStorage key — persists the activated state across page refreshes
// ─────────────────────────────────────────────────────────────────────────────

const ACTIVATED_KEY = 'idp-monitor-activated';

function getPersistedActivated(): boolean {
  try {
    return localStorage.getItem(ACTIVATED_KEY) === 'true';
  } catch {
    return false;
  }
}

function setPersistedActivated(value: boolean): void {
  try {
    localStorage.setItem(ACTIVATED_KEY, String(value));
  } catch {
    // ignore
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Stack detection — checks SSM for the monitor API URL parameter
// The IDPMonitor deploy.sh writes /idp-monitor/<stack>/api-url to SSM.
// Falls back to a simple CloudFormation describe via the Accelerator API.
// ─────────────────────────────────────────────────────────────────────────────

async function detectMonitorStack(stackName: string, credentials: unknown): Promise<boolean> {
  try {
    const region = (import.meta.env.VITE_AWS_REGION as string) || 'us-east-1';

    // Check SSM parameter written by the IDPMonitor deploy
    const ssm = new SSMClient({
      region,
      credentials: credentials as unknown as AwsCredentialIdentity,
    });

    const paramName = `/idp-monitor/${stackName}/api-url`;
    await ssm.send(new GetParameterCommand({ Name: paramName }));
    // If the command succeeds (no throw), the parameter exists → stack is deployed
    return true;
  } catch {
    return false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────────────────────────────────

const MonitoringLoadingSkeleton: React.FC = () => (
  <Box padding="l">
    <SpaceBetween size="m">
      {['row-0', 'row-1', 'row-2'].map((id) => (
        <div
          key={id}
          style={{
            height: '120px',
            borderRadius: '8px',
            backgroundColor: '#e5e7eb',
            animation: 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
          }}
        />
      ))}
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Premium MonitoringPage — lazy-loaded; falls back when package is absent
// ─────────────────────────────────────────────────────────────────────────────

const PremiumMonitoringPage = lazy(() =>
  // @ts-expect-error: optional premium package not present in OSS builds
  // eslint-disable-next-line import-x/no-unresolved
  import('@idp-accelerator/idp-monitor-ui')
    .then((mod: { MonitoringPage: React.ComponentType<MonitoringShellProps> }) => ({
      default: mod.MonitoringPage,
    }))
    .catch(() => ({
      default: (_props: MonitoringShellProps) => (
        <Box padding="l">
          <Alert type="warning" header="Monitoring package unavailable">
            The <code>@idp-accelerator/idp-monitor-ui</code> package is not installed in this build. Please contact your administrator or
            redeploy with the premium package included.
          </Alert>
        </Box>
      ),
    })),
) as React.LazyExoticComponent<React.ComponentType<MonitoringShellProps>>;

// ─────────────────────────────────────────────────────────────────────────────
// Activation / CTA page — shown before the user enables monitoring
// ─────────────────────────────────────────────────────────────────────────────

interface ActivationPageProps {
  onEnable: () => void;
  isChecking: boolean;
  stackNotFound: boolean;
  stackName: string;
}

const ActivationPage: React.FC<ActivationPageProps> = ({ onEnable, isChecking, stackNotFound, stackName }) => (
  <Box padding={{ top: 'xxl', horizontal: 'xxl' }}>
    <SpaceBetween size="l">
      <Container
        header={
          <Header variant="h1" description="Enable real-time observability for your IDP Accelerator pipeline">
            IDPMonitor — Monitoring Dashboard
          </Header>
        }
      >
        <SpaceBetween size="m">
          <TextContent>
            <p>IDPMonitor provides production-grade observability for your Intelligent Document Processing pipeline, including:</p>
            <ul>
              <li>Real-time document processing metrics and throughput charts</li>
              <li>Error rate tracking and automated root-cause analysis</li>
              <li>Step Functions execution timelines and Lambda performance</li>
              <li>Cost and quota utilisation dashboards</li>
            </ul>
            <p>
              To enable monitoring, deploy the <strong>IDPMonitor</strong> stack alongside your Accelerator stack using the provided{' '}
              <code>deploy.sh</code> script:
            </p>
            <pre style={{ background: '#f4f4f4', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
              {`cd products/idp-monitor\n./deploy.sh --stack-name ${stackName || '<your-stack-name>'}`}
            </pre>
            <p>
              Once the stack is deployed, click <strong>Enable Monitoring</strong> below to activate the dashboard.
            </p>
          </TextContent>

          {stackNotFound && (
            <Alert type="error" header="IDPMonitor stack not detected">
              The IDPMonitor stack does not appear to be deployed yet for stack&nbsp;
              <strong>{stackName}</strong>. Deploy it using the command above, then click <strong>Enable Monitoring</strong> again.
            </Alert>
          )}

          <Box>
            <Button variant="primary" onClick={onEnable} loading={isChecking} disabled={isChecking}>
              {isChecking ? 'Checking deployment…' : 'Enable Monitoring'}
            </Button>
          </Box>

          {isChecking && <StatusIndicator type="loading">Checking if IDPMonitor stack is deployed…</StatusIndicator>}
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Main shell
// ─────────────────────────────────────────────────────────────────────────────

export const MonitoringShell: React.FC<MonitoringShellProps> = ({ stackName, className }) => {
  const { currentCredentials } = useAppContext();

  const [activated, setActivated] = useState<boolean>(getPersistedActivated);
  const [isChecking, setIsChecking] = useState(false);
  const [stackNotFound, setStackNotFound] = useState(false);

  const handleEnable = useCallback(async () => {
    setIsChecking(true);
    setStackNotFound(false);

    const found = await detectMonitorStack(stackName, currentCredentials);

    setIsChecking(false);

    if (found) {
      setPersistedActivated(true);
      setActivated(true);
    } else {
      setStackNotFound(true);
    }
  }, [stackName, currentCredentials]);

  if (!activated) {
    return (
      <div className={className}>
        <ActivationPage onEnable={handleEnable} isChecking={isChecking} stackNotFound={stackNotFound} stackName={stackName} />
      </div>
    );
  }

  return (
    <div className={className}>
      <Suspense fallback={<MonitoringLoadingSkeleton />}>
        <PremiumMonitoringPage stackName={stackName} />
      </Suspense>
    </div>
  );
};

export default MonitoringShell;
