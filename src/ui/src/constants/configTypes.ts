// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Configuration type constants.
 *
 * These constants define the valid configuration types used throughout the system.
 * Use these instead of hardcoded strings to ensure consistency with backend.
 *
 * IMPORTANT: These must match the values in:
 * lib/idp_common_pkg/idp_common/config/constants.py
 */

// Configuration Types
export const CONFIG_TYPE_SCHEMA = 'Schema';
export const CONFIG_TYPE_DEFAULT = 'Default';
export const CONFIG_TYPE_CUSTOM = 'Custom';

// All valid configuration types
export const VALID_CONFIG_TYPES = [CONFIG_TYPE_SCHEMA, CONFIG_TYPE_DEFAULT, CONFIG_TYPE_CUSTOM] as const;

export type ConfigType = (typeof VALID_CONFIG_TYPES)[number];
