// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

export const deepMerge = (target: Record<string, unknown>, source: Record<string, unknown> | undefined | null): Record<string, unknown> => {
  const result: Record<string, unknown> = { ...target };

  if (!source) {
    return result;
  }

  Object.keys(source)
    .filter((key) => Object.hasOwn(source, key))
    .forEach((key) => {
      if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
        if (Object.hasOwn(target, key) && target[key] && typeof target[key] === 'object') {
          result[key] = deepMerge(target[key] as Record<string, unknown>, source[key] as Record<string, unknown>);
        } else {
          result[key] = { ...(source[key] as Record<string, unknown>) };
        }
      } else {
        result[key] = source[key];
      }
    });

  return result;
};
