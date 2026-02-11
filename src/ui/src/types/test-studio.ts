// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface TestRun {
  testRunId: string;
  testSetId: string;
  testSetName: string;
  status: string;
  filesCount: number;
  createdAt: string;
  completedAt: string;
  context: string;
}

export interface TestSet {
  id: string;
  name: string;
  description: string;
  filePattern: string;
  fileCount: number;
  status: string;
  createdAt: string;
  error: string;
}

export interface ActiveTestRun {
  testRunId: string;
  status: string;
}
