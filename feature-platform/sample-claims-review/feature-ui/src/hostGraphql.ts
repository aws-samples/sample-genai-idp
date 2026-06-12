// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Calls the HOST's AppSync GraphQL API directly from the feature UI.
 *
 * This works because the host installs `window.awsAmplify` (see
 * src/ui/src/components/feature-page/feature-host-globals.ts) — the SAME
 * configured, signed-in Amplify instance the host UI uses. `generateClient()`
 * therefore inherits the user's Cognito session and talks to the host's
 * GraphQL endpoint with the user's own JWT and group memberships. No extra
 * configuration is needed in the feature.
 *
 * We use this for the Rules Discovery flow, which is built entirely on host
 * mutations/queries (uploadDiscoveryDocument, listDiscoveryJobs,
 * getConfigVersion). The feature contributes the UI; the host owns the
 * discovery pipeline and the config it writes to.
 *
 * NOTE on auth: uploadDiscoveryDocument is restricted to the Admin/Author
 * Cognito groups (see schema.graphql). A Reviewer-role user will get an
 * authorization error — the RulesDiscoveryView surfaces that as a friendly
 * "needs Admin or Author" message rather than a raw GraphQL error.
 */

import { generateClient } from 'aws-amplify/api';

const client = generateClient();

const UPLOAD_DISCOVERY_DOCUMENT = /* GraphQL */ `
  mutation UploadDiscoveryDocument(
    $fileName: String!
    $contentType: String
    $bucket: String
    $version: String
    $discoveryType: String
  ) {
    uploadDiscoveryDocument(
      fileName: $fileName
      contentType: $contentType
      bucket: $bucket
      version: $version
      discoveryType: $discoveryType
    ) {
      presignedUrl
      objectKey
      usePostMethod
    }
  }
`;

const LIST_DISCOVERY_JOBS = /* GraphQL */ `
  query ListDiscoveryJobs {
    listDiscoveryJobs {
      DiscoveryJobs {
        jobId
        documentKey
        status
        statusMessage
        createdAt
        updatedAt
        errorMessage
        version
        discoveryType
        jobType
      }
    }
  }
`;

const GET_CONFIG_VERSION = /* GraphQL */ `
  query GetConfigVersion($versionName: String!) {
    getConfigVersion(versionName: $versionName) {
      success
      Custom
      Default
    }
  }
`;

export interface DiscoveryJob {
  jobId: string;
  documentKey?: string;
  status: string;
  statusMessage?: string;
  createdAt?: string;
  updatedAt?: string;
  errorMessage?: string;
  version?: string;
  discoveryType?: string;
  jobType?: string;
}

export interface PresignedUpload {
  presignedUrl: string;
  objectKey: string;
  usePostMethod: string;
}

type GraphQLResult<T> = { data?: T; errors?: Array<{ message: string }> };

function unwrap<T>(result: unknown): T {
  const r = result as GraphQLResult<T>;
  if (r.errors?.length) {
    throw new Error(r.errors.map((e) => e.message).join('; '));
  }
  if (!r.data) throw new Error('Empty GraphQL response');
  return r.data;
}

/**
 * Request a presigned upload for a policy document, creating a `rules`
 * discovery job. `version` is the config version the discovered policy
 * classes are written into (the claims preset version).
 */
export async function uploadDiscoveryDocument(args: {
  fileName: string;
  contentType: string;
  bucket: string;
  version: string;
}): Promise<PresignedUpload> {
  const result = await client.graphql({
    query: UPLOAD_DISCOVERY_DOCUMENT,
    variables: { ...args, discoveryType: 'rules' },
  });
  const data = unwrap<{ uploadDiscoveryDocument: PresignedUpload }>(result);
  return data.uploadDiscoveryDocument;
}

/** PUT/POST the file to S3 using the presigned POST data the host returned. */
export async function uploadToS3(
  file: File,
  presignedUrl: string,
): Promise<void> {
  const presignedPostData = JSON.parse(presignedUrl) as {
    url: string;
    fields: Record<string, string>;
  };
  const formData = new FormData();
  Object.entries(presignedPostData.fields).forEach(([key, value]) => {
    formData.append(key, value);
  });
  formData.append('file', file);
  const resp = await fetch(presignedPostData.url, {
    method: 'POST',
    body: formData,
  });
  if (!resp.ok) {
    throw new Error(`S3 upload failed: HTTP ${resp.status}`);
  }
}

/** List discovery jobs, filtered to `rules` jobs (the ones this view drives). */
export async function listRulesDiscoveryJobs(): Promise<DiscoveryJob[]> {
  const result = await client.graphql({ query: LIST_DISCOVERY_JOBS });
  const data = unwrap<{ listDiscoveryJobs?: { DiscoveryJobs?: DiscoveryJob[] } }>(
    result,
  );
  const jobs = data.listDiscoveryJobs?.DiscoveryJobs ?? [];
  return jobs.filter(
    (j) => j.discoveryType === 'rules' || j.jobType === 'rules',
  );
}

export interface PolicyRule {
  name: string;
  description?: string;
}

export interface PolicyClass {
  policyType: string;
  description?: string;
  rules: PolicyRule[];
}

/**
 * Read the config version the discovery job wrote into and pull out the
 * `policy_classes`. Each class carries `x-aws-idp-policy-type` plus a
 * `rule_properties` map (ruleName -> { description }). The configuration
 * resolver returns Custom/Default as JSON-encoded strings.
 */
export async function getPolicyClasses(versionName: string): Promise<PolicyClass[]> {
  const result = await client.graphql({
    query: GET_CONFIG_VERSION,
    variables: { versionName },
  });
  const data = unwrap<{
    getConfigVersion?: { success: boolean; Custom?: string; Default?: string };
  }>(result);
  const raw = data.getConfigVersion?.Custom || data.getConfigVersion?.Default;
  if (!raw) return [];
  let config: Record<string, unknown>;
  try {
    config = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return [];
  }
  const policyClasses = config.policy_classes;
  if (!Array.isArray(policyClasses)) return [];
  return policyClasses.map((pc) => {
    const entry = pc as Record<string, unknown>;
    const policyType =
      (entry['x-aws-idp-policy-type'] as string) ||
      (entry.$id as string) ||
      'unknown';
    const ruleProps = entry.rule_properties;
    const rules: PolicyRule[] =
      ruleProps && typeof ruleProps === 'object'
        ? Object.entries(ruleProps as Record<string, unknown>).map(
            ([name, def]) => ({
              name,
              description:
                def && typeof def === 'object'
                  ? ((def as Record<string, unknown>).description as string)
                  : undefined,
            }),
          )
        : [];
    return {
      policyType,
      description:
        typeof entry.description === 'string' ? entry.description : undefined,
      rules,
    };
  });
}
