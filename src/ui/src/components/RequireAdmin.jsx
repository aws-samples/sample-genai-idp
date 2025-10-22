// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { Redirect } from 'react-router-dom';
import { Container, Header, SpaceBetween } from '@awsui/components-react';
import useAppContext from '../contexts/app';
import { DOCUMENTS_PATH } from '../routes/constants';

/**
 * Route guard component that restricts access to admin-only routes
 * Redirects regular users to the documents page with an error message
 */
const RequireAdmin = ({ children }) => {
  const { isAdmin } = useAppContext();

  if (!isAdmin) {
    return (
      <Container>
        <SpaceBetween size="l">
          <Header variant="h1">Access Denied</Header>
          <p>You do not have permission to access this page. This feature is only available to administrators.</p>
          <p>Redirecting to documents...</p>
        </SpaceBetween>
        <Redirect to={DOCUMENTS_PATH} />
      </Container>
    );
  }

  return children;
};

RequireAdmin.propTypes = {
  children: PropTypes.node.isRequired,
};

export default RequireAdmin;
