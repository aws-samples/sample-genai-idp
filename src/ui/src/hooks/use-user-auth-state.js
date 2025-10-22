// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useAuthenticator } from '@aws-amplify/ui-react';
import { Logger } from 'aws-amplify';

const logger = new Logger('useUserAuthState');

const useUserAuthState = () => {
  const { authStatus, user } = useAuthenticator((context) => [context.authStatus, context.user]);

  logger.debug('auth status:', authStatus);
  logger.debug('auth user:', user);

  // Extract user groups and role information
  let groups = [];
  let isAdmin = false;

  if (user?.signInUserSession) {
    const { clientId } = user.pool;
    const { idToken, accessToken, refreshToken } = user.signInUserSession;

    // prettier-ignore
    localStorage.setItem(`${clientId}idtokenjwt`, idToken.jwtToken);
    // prettier-ignore
    localStorage.setItem(`${clientId}accesstokenjwt`, accessToken.jwtToken);
    // prettier-ignore
    localStorage.setItem(`${clientId}refreshtoken`, refreshToken.token);

    // Extract groups from access token
    groups = accessToken?.payload['cognito:groups'] || [];
    isAdmin = groups.includes('Admin');

    logger.debug('User groups:', groups);
    logger.debug('Is admin:', isAdmin);
  }

  return {
    authState: authStatus,
    user,
    groups,
    isAdmin,
  };
};

export default useUserAuthState;
