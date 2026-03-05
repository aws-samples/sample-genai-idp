// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useEffect } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';

interface UserRoleReturn {
  groups: string[];
  isAdmin: boolean;
  isSupervisor: boolean;
  isReviewer: boolean;
  loading: boolean;
}

const useUserRole = (): UserRoleReturn => {
  const [groups, setGroups] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchGroups = async () => {
      try {
        const session = await fetchAuthSession();
        const userGroups = session?.tokens?.idToken?.payload?.['cognito:groups'] || [];
        setGroups(Array.isArray(userGroups) ? (userGroups as string[]) : [userGroups as string]);
      } catch (error) {
        console.error('Error fetching user groups:', error);
        setGroups([]);
      } finally {
        setLoading(false);
      }
    };
    fetchGroups();
  }, []);

  const isAdmin = groups.includes('Admin');
  const isSupervisor = groups.includes('Supervisor');
  const isReviewer = groups.includes('Reviewer');

  return { groups, isAdmin, isSupervisor, isReviewer, loading };
};

export default useUserRole;
