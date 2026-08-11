// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * The document classes a config version defines, as dropdown options.
 *
 * Shared by human review (SectionsPanel) and Test Studio annotation
 * (GroundTruthVisualEditor): both let a user correct a misclassified section, and
 * both must offer exactly the classes the bound config knows about — a free-text
 * class that the config has no schema for cannot be extracted against.
 */

export interface ConfigClassOption {
  label: string;
  value: string;
  description?: string;
}

interface ConfigWithClasses {
  classes?: unknown;
}

/**
 * Handles both config shapes in the wild: JSON Schema classes name themselves
 * with `$id` or `x-aws-idp-document-type`, pre-migration ones with `name`.
 * Descriptions come along so the class can be chosen without leaving the
 * dropdown.
 */
export const getConfigClassOptions = (config?: ConfigWithClasses | null): ConfigClassOption[] => {
  const classes = config?.classes;
  if (!Array.isArray(classes)) return [];
  return (classes as Record<string, unknown>[])
    .map((cls) => {
      const className = String(cls.$id || cls['x-aws-idp-document-type'] || cls.name || '');
      const description = typeof cls.description === 'string' ? cls.description.trim() : '';
      return { label: className, value: className, description: description || undefined };
    })
    .filter((option) => option.value);
};

export default getConfigClassOptions;
