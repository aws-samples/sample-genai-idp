// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import useSettingsContext from '../contexts/settings';
import type { DeploymentContext } from '../utils/github-feedback';

/**
 * Assembles the current deployment's environment details (version, region,
 * stack, pattern, build date) from the SSM-backed settings context and the
 * build-time region env var. Used to pre-fill GitHub feedback/issue forms so
 * users don't have to hand-type their deployment info.
 */
const useDeploymentContext = (): DeploymentContext => {
  const { settings } = useSettingsContext();
  const s = settings as Record<string, unknown> | undefined;

  return {
    version: s?.Version as string | undefined,
    region: import.meta.env.VITE_AWS_REGION as string | undefined,
    stackName: s?.StackName as string | undefined,
    pattern: s?.IDPPattern as string | undefined,
    buildDateTime: s?.BuildDateTime as string | undefined,
  };
};

export default useDeploymentContext;
