// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

interface GraphQLError {
  message?: string;
  errors?: { message?: string }[];
}

export const getErrorMessage = (err: unknown): string => {
  if (err instanceof Error) return err.message;
  const gqlErr = err as GraphQLError;
  return gqlErr?.message || gqlErr?.errors?.[0]?.message || JSON.stringify(err) || 'Unknown error';
};
