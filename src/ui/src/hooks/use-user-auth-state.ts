// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useAuthenticator } from '@aws-amplify/ui-react';
import { ConsoleLogger } from 'aws-amplify/utils';

const logger = new ConsoleLogger('useUserAuthState');

interface LegacyAuthUser {
  signInUserSession?: {
    idToken: { jwtToken: string };
    accessToken: { jwtToken: string };
    refreshToken: { token: string };
  };
  pool?: { clientId: string };
}

const useUserAuthState = (): { authState: string; user: ReturnType<typeof useAuthenticator>['user'] } => {
  const { authStatus, user } = useAuthenticator((context) => [context.authStatus, context.user]);

  logger.debug('auth status:', authStatus);
  logger.debug('auth user:', user);

  const legacyUser = user as unknown as LegacyAuthUser;
  if (legacyUser?.signInUserSession) {
    const { clientId } = legacyUser.pool!;
    const { idToken, accessToken, refreshToken } = legacyUser.signInUserSession;

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
