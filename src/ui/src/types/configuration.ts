// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface ValidationError {
  field: string;
  message: string;
  type?: string;
}

export interface ConfigurationError {
  type: string;
  message: string;
  validationErrors?: ValidationError[];
}

export interface ConfigurationResponse {
  success: boolean;
  Schema: string | Record<string, unknown> | null;
  Default: string | Record<string, unknown> | null;
  Custom: string | Record<string, unknown> | null;
  error?: ConfigurationError;
}
