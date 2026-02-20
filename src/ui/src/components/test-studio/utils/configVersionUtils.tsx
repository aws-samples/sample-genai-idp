// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Link } from '@cloudscape-design/components';

export interface ConfigVersion {
  version?: string;
  versionName: string;
  description?: string;
  created?: string;
  isActive?: boolean;
  [key: string]: unknown;
}

export const formatConfigVersionLink = (
  configVersion: string | null | undefined,
  versions: ConfigVersion[],
  _maxDescLength = 10,
): React.JSX.Element | string => {
  if (!configVersion) return 'N/A';

  const versionFromList = versions.find((v) => v.versionName === configVersion);

  // If version not found in current versions list, show as deleted
  if (!versionFromList) {
    return <span style={{ textDecoration: 'line-through', color: '#687078' }}>{configVersion}</span>;
  }

  return <Link href={`#/documents/config?version=${configVersion}`}>{configVersion}</Link>;
};

export const formatConfigVersionText = (configVersion: string | null | undefined, versions: ConfigVersion[]): string => {
  if (!configVersion) return 'N/A';

  const versionFromList = versions.find((v) => v.versionName === configVersion);

  // If version not found in current versions list, show as deleted
  if (!versionFromList) {
    return `${configVersion} (deleted)`;
  }

  return configVersion;
};
