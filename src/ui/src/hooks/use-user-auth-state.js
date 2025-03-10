// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useAuthenticator } from '@aws-amplify/ui-react';
import { Logger } from 'aws-amplify';

const logger = new Logger('useUserAuthState');

const useUserAuthState = () => {
  const { authStatus, user } = useAuthenticator((context) => [context.authStatus, context.user]);

  logger.debug('auth status:', authStatus);
  logger.debug('auth user:', user);

  if (user?.signInUserSession) {
    const { clientId } = user.pool;
    const { idToken, accessToken, refreshToken } = user.signInUserSession;

    // prettier-ignore
    localStorage.setItem(`${clientId}idtokenjwt`, idToken.jwtToken);
    // prettier-ignore
    localStorage.setItem(`${clientId}accesstokenjwt`, accessToken.jwtToken);
    // prettier-ignore
    localStorage.setItem(`${clientId}refreshtoken`, refreshToken.token);
  }

  return { authState: authStatus, user };
};

export default useUserAuthState;
