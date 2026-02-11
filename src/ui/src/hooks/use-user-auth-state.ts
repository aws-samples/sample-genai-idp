// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useAuthenticator } from '@aws-amplify/ui-react';
import { ConsoleLogger } from 'aws-amplify/utils';

const logger = new ConsoleLogger('useUserAuthState');

const useUserAuthState = (): { authState: string; user: any } => {
  const { authStatus, user } = useAuthenticator((context) => [context.authStatus, context.user]);

  logger.debug('auth status:', authStatus);
  logger.debug('auth user:', user);

  const userAny = user as any;
  if (userAny?.signInUserSession) {
    const { clientId } = userAny.pool;
    const { idToken, accessToken, refreshToken } = userAny.signInUserSession;

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
