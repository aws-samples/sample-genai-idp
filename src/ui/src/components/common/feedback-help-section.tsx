// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Icon } from '@cloudscape-design/components';

import useDeploymentContext from '../../hooks/use-deployment-context';
import { buildBugReportUrl, buildFeatureRequestUrl } from '../../utils/github-feedback';
import { GITHUB_ISSUES_URL } from '../../constants/github';

/**
 * Reusable "Feedback & support" block for HelpPanel (right-side info) content.
 * Renders links that pre-fill the GitHub issue forms with the current
 * deployment's environment details. Embed inside any tools-panel's body.
 */
const FeedbackHelpSection = (): React.JSX.Element => {
  const deploymentContext = useDeploymentContext();
  const bugReportUrl = buildBugReportUrl(deploymentContext);
  const featureRequestUrl = buildFeatureRequestUrl(deploymentContext);

  return (
    <div>
      <h3>Feedback &amp; support</h3>
      <p>Report bugs or suggest enhancements on GitHub — your deployment details are filled in automatically.</p>
      <ul>
        <li>
          <a href={bugReportUrl} target="_blank" rel="noopener noreferrer">
            Report a bug <Icon name="external" />
          </a>
        </li>
        <li>
          <a href={featureRequestUrl} target="_blank" rel="noopener noreferrer">
            Request a feature <Icon name="external" />
          </a>
        </li>
        <li>
          <a href={GITHUB_ISSUES_URL} target="_blank" rel="noopener noreferrer">
            View existing issues <Icon name="external" />
          </a>
        </li>
      </ul>
      <p>
        For document-processing failures, run the <strong>Troubleshoot</strong> agent on a failed document and use{' '}
        <strong>Report this issue on GitHub</strong> to attach its findings. Issues are public — please redact sensitive data before
        submitting.
      </p>
    </div>
  );
};

export default FeedbackHelpSection;
