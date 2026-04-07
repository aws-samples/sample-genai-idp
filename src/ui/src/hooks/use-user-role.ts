// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useEffect } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { generateClient } from 'aws-amplify/api';
import { getMyProfile } from '../graphql/generated';

/**
 * RBAC Role Definitions:
 *   Admin    - Full access to all operations
 *   Author   - Read + write (documents, configuration, tests, discovery)
 *   Reviewer - HITL review operations + limited document list (server-side filtered)
 *   Viewer   - Read-only access to documents, config, agent chat, code explorer
 *
 * Users can be in multiple groups (union of permissions applies).
 * Users can optionally have allowedConfigVersions for config-version scoping.
 */
interface UserRoleReturn {
  groups: string[];
  isAdmin: boolean;
  isAuthor: boolean;
  isReviewer: boolean;
  isViewer: boolean;
  /** True if user is ONLY in the Reviewer group (no Admin/Author/Viewer) */
  isReviewerOnly: boolean;
  /** True if user is ONLY in the Viewer group (no Admin/Author) */
  isViewerOnly: boolean;
  /** True if user can write (Admin or Author) */
  canWrite: boolean;
  /** True if user can manage users (Admin only) */
  canManageUsers: boolean;
  /** True if user can delete config versions (Admin only) */
  canDeleteConfig: boolean;
  /** True if user can perform HITL reviews (Admin or Reviewer) */
  canReview: boolean;
  /** Config versions the user is allowed to access. null/undefined = unrestricted (all versions). */
  allowedConfigVersions: string[] | null;
  loading: boolean;
}

const useUserRole = (): UserRoleReturn => {
  const [groups, setGroups] = useState<string[]>([]);
  const [allowedConfigVersions, setAllowedConfigVersions] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchUserData = async () => {
      try {
        // Fetch Cognito groups from auth session
        const session = await fetchAuthSession();
        const userGroups = session?.tokens?.idToken?.payload?.['cognito:groups'] || [];
        let groupsArray = Array.isArray(userGroups) ? (userGroups as string[]) : [userGroups as string];

        // For federated users on first login, groups may not be in the initial token.
        // Force a single token refresh to pick up groups assigned by the PreTokenGeneration Lambda.
        // This only runs once (empty deps array) so it won't cause excessive refresh calls.
        const isFederated = (session?.tokens?.idToken?.payload?.['identities'] as string | undefined) !== undefined;
        const appGroups = groupsArray.filter((g) => ['Admin', 'Author', 'Reviewer', 'Viewer'].includes(g));
        if (isFederated && appGroups.length === 0) {
          try {
            const refreshed = await fetchAuthSession({ forceRefresh: true });
            const refreshedGroups = refreshed?.tokens?.idToken?.payload?.['cognito:groups'] || [];
            groupsArray = Array.isArray(refreshedGroups) ? (refreshedGroups as string[]) : [refreshedGroups as string];
          } catch (refreshErr) {
            console.warn('Token refresh for federated group sync failed:', refreshErr);
          }
        }

        setGroups(groupsArray);

        // Fetch user profile for allowedConfigVersions (skip for Admin - always unrestricted)
        if (!groupsArray.includes('Admin')) {
          try {
            const client = generateClient();
            const result = await client.graphql({ query: getMyProfile });
            const profile = result.data.getMyProfile;
            if (profile?.allowedConfigVersions && profile.allowedConfigVersions.length > 0) {
              const versions = profile.allowedConfigVersions.filter((v): v is string => v !== null);
              setAllowedConfigVersions(versions.length > 0 ? versions : null);
            }
          } catch (profileErr) {
            console.warn('Could not fetch user profile for scope:', profileErr);
            // Non-critical - default to unrestricted
          }
        }
      } catch (error) {
        console.error('Error fetching user role:', error);
        setGroups([]);
      } finally {
        setLoading(false);
      }
    };
    fetchUserData();
  }, []);

  const isAdmin = groups.includes('Admin');
  const isAuthor = groups.includes('Author');
  const isReviewer = groups.includes('Reviewer');
  const isViewer = groups.includes('Viewer');

  // Derived convenience flags
  const isReviewerOnly = isReviewer && !isAdmin && !isAuthor && !isViewer;
  const isViewerOnly = isViewer && !isAdmin && !isAuthor;
  const canWrite = isAdmin || isAuthor;
  const canManageUsers = isAdmin;
  const canDeleteConfig = isAdmin;
  const canReview = isAdmin || isReviewer;

  return {
    groups,
    isAdmin,
    isAuthor,
    isReviewer,
    isViewer,
    isReviewerOnly,
    isViewerOnly,
    canWrite,
    canManageUsers,
    canDeleteConfig,
    canReview,
    allowedConfigVersions,
    loading,
  };
};

export default useUserRole;
