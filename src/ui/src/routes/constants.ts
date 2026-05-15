// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
export const LOGIN_PATH = '/login';
export const LOGOUT_PATH = '/logout';
export const DOCUMENTS_PATH = '/documents';
export const TEST_STUDIO_PATH = '/test-studio';
export const DEFAULT_PATH = DOCUMENTS_PATH;
export const REDIRECT_URL_PARAM = 'redirect';
export const DOCUMENTS_KB_QUERY_PATH = `${DOCUMENTS_PATH}/query`;
export const DOCUMENTS_ANALYTICS_PATH = `${DOCUMENTS_PATH}/agents`;
export const CONFIGURATION_PATH = `${DOCUMENTS_PATH}/config`;
export const PRICING_PATH = `${DOCUMENTS_PATH}/pricing`;
export const UPLOAD_DOCUMENT_PATH = `${DOCUMENTS_PATH}/upload`;
export const DISCOVERY_PATH = `${DOCUMENTS_PATH}/discovery`;
export const DISCOVERY_JOB_PATH = `${DOCUMENTS_PATH}/discovery/job`;
export const USER_MANAGEMENT_PATH = `${DOCUMENTS_PATH}/users`;
export const AGENT_CHAT_PATH = '/agentchat';
export const CAPACITY_PLANNING_PATH = `${DOCUMENTS_PATH}/capacity-planning`;
export const CUSTOM_MODELS_PATH = `${DOCUMENTS_PATH}/custom-models`;

// --- Feature Platform ---
export const FEATURES_PATH_PREFIX = '/features';
/** Route pattern: /features/:featureId */
export const FEATURE_DETAIL_PATH = `${FEATURES_PATH_PREFIX}/:featureId`;
/** Hash-link helper: href to pass to nav items & internal links. */
export const featureDetailHref = (featureId: string): string => `#${FEATURES_PATH_PREFIX}/${featureId}`;
export const MONITORING_PATH = '/monitoring';
