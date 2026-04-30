// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringActivationPage — shown when the user navigates to /monitoring
 * but the IDPMonitor stack has not been deployed yet.
 *
 * This is a built-in static component — it has NO dependency on the
 * @idp-accelerator/idp-monitor-ui package. The IDP Accelerator builds and
 * deploys independently of the IDPMonitor stack.
 *
 * The monitoring dashboard UI is loaded at RUNTIME from the Accelerator's
 * S3/CloudFront origin once the IDPMonitor stack has been deployed and
 * deploy.sh has copied the UI bundle and patched the SSM settings parameter.
 */

import React from 'react';
import { Alert, Box, Button, Container, Header, SpaceBetween, TextContent } from '@cloudscape-design/components';

interface MonitoringActivationPageProps {
  /** Stack name to display in the deploy command. */
  stackName?: string;
  /** Called when the user clicks "I already deployed it" to force a page refresh. */
  onRefresh?: () => void;
  /** Optional CSS class for the wrapper. */
  className?: string;
}

export const MonitoringActivationPage: React.FC<MonitoringActivationPageProps> = ({ stackName, onRefresh, className }) => (
  <div
    className={className}
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'flex-start',
      padding: '2rem',
    }}
  >
    <div style={{ maxWidth: '700px', width: '100%' }}>
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
              <Alert type="info">
                The <strong>IDPMonitor</strong> stack has not been deployed yet, or the monitoring configuration has not been written to
                your Accelerator settings.
              </Alert>

              <TextContent>
                <h3>Getting Started</h3>
                <p>
                  Deploy the <strong>IDPMonitor</strong> stack alongside your existing Accelerator stack using the <code>deploy.sh</code>{' '}
                  script:
                </p>
                <pre
                  style={{
                    background: '#f4f4f4',
                    padding: '0.75rem',
                    borderRadius: '4px',
                    fontSize: '0.85rem',
                    overflow: 'auto',
                  }}
                >
                  {`cd products/idp-monitor\n./deploy.sh --stack-name ${stackName || '<your-accelerator-stack-name>'}`}
                </pre>
                <p>The deploy script will automatically:</p>
                <ol>
                  <li>Deploy the AppSync monitoring API and backend Lambda functions</li>
                  <li>Copy the monitoring UI bundle to your Accelerator&apos;s S3 bucket</li>
                  <li>Update your Accelerator SSM settings with the monitoring endpoint</li>
                  <li>Invalidate the CloudFront cache</li>
                </ol>
                <p>
                  Once complete, <strong>refresh this page</strong> — the monitoring dashboard will load automatically without requiring a
                  rebuild or redeployment of the Accelerator.
                </p>
              </TextContent>

              {onRefresh && (
                <Box>
                  <Button variant="primary" onClick={onRefresh}>
                    {'I deployed IDPMonitor \u2014 Refresh'}
                  </Button>
                </Box>
              )}
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Box>
    </div>
  </div>
);

export default MonitoringActivationPage;
