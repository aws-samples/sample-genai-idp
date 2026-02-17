// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Button,
  Alert,
  Table,
  Modal,
  Form,
  FormField,
  Input,
  Select,
  StatusIndicator,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import useUserRole from '../../hooks/use-user-role';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import listUsers from '../../graphql/queries/listUsers';
import createUserMutation from '../../graphql/mutations/createUser';
import deleteUserMutation from '../../graphql/mutations/deleteUser';

const logger = new ConsoleLogger('UserManagementLayout');

interface User {
  userId: string;
  email: string;
  persona: string;
  status?: string;
  createdAt?: string;
}

const UserManagementLayout = (): React.JSX.Element => {
  const { awsConfig } = useAppContext();
  const { settings } = useSettingsContext();
  const { isAdmin, loading: roleLoading } = useUserRole();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [email, setEmail] = useState('');
  const [persona, setPersona] = useState('Reviewer');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [emailError, setEmailError] = useState('');

  const allowedDomains = useMemo(() => {
    const domains = ((settings as Record<string, unknown>)?.AllowedSignUpEmailDomains as string) || '';
    return domains
      ? domains
          .split(',')
          .map((d) => d.trim().toLowerCase())
          .filter(Boolean)
      : [];
  }, [settings]);

  const personaOptions = [
    { label: 'Admin', value: 'Admin' },
    { label: 'Reviewer', value: 'Reviewer' },
  ];

  const validateEmail = useCallback(
    (emailValue: string): string => {
      if (!emailValue) {
        return '';
      }
      const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
      if (!emailPattern.test(emailValue)) {
        return 'Invalid email format';
      }
      if (allowedDomains.length > 0) {
        const domain = emailValue.split('@')[1]?.toLowerCase();
        if (!allowedDomains.includes(domain)) {
          return `Email domain must be one of: ${allowedDomains.join(', ')}`;
        }
      }
      return '';
    },
    [allowedDomains],
  );

  const handleEmailChange = ({ detail }: { detail: { value: string } }): void => {
    setEmail(detail.value);
    setEmailError(validateEmail(detail.value));
  };

  const loadUsers = useCallback(
    async (showRefreshing = false) => {
      if (!awsConfig) {
        logger.debug('AWS config not ready, skipping loadUsers');
        return;
      }

      if (showRefreshing) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError('');

      try {
        const client = generateClient();
        logger.debug('Loading users...');
        const result = await client.graphql({ query: listUsers as unknown as string });
        const usersList =
          (((result as { data: Record<string, unknown> }).data?.listUsers as Record<string, unknown>)?.users as User[]) || [];
        logger.debug(`Loaded ${usersList.length} users`);
        setUsers(usersList);
      } catch (err) {
        logger.error('Failed to load users:', err);
        const errorMessage = err.errors?.[0]?.message || err.message || 'Unknown error';
        setError(`Failed to load users: ${errorMessage}`);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [awsConfig],
  );

  const createUser = async () => {
    if (!email) {
      setError('Email is required');
      return;
    }

    const validationError = validateEmail(email);
    if (validationError) {
      setEmailError(validationError);
      return;
    }

    if (!awsConfig) {
      setError('Configuration not ready');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');

    try {
      const client = generateClient();
      logger.debug('Creating user:', { email, persona });
      await client.graphql({
        query: createUserMutation,
        variables: { email, persona },
      });

      logger.debug('User created successfully');
      setSuccess(`User ${email} created successfully`);
      setShowCreateModal(false);
      setEmail('');
      setPersona('Reviewer');
      await loadUsers();
    } catch (err) {
      logger.error('Failed to create user:', err);
      // Extract error message from GraphQL error structure
      const errorMessage = err.errors?.[0]?.message || err.message || 'Unknown error';
      setError(`Failed to create user: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const deleteUser = async (userId: string, userEmail: string): Promise<void> => {
    if (!window.confirm(`Are you sure you want to delete user ${userEmail}?`)) {
      return;
    }

    if (!awsConfig) {
      setError('Configuration not ready');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');

    try {
      const client = generateClient();
      logger.debug('Deleting user:', userId);
      await client.graphql({
        query: deleteUserMutation,
        variables: { userId },
      });

      logger.debug('User deleted successfully');
      setSuccess(`User ${userEmail} deleted successfully`);
      await loadUsers();
    } catch (err) {
      logger.error('Failed to delete user:', err);
      const errorMessage = err.errors?.[0]?.message || err.message || 'Unknown error';
      setError(`Failed to delete user: ${errorMessage}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateModalClose = () => {
    setShowCreateModal(false);
    setEmail('');
    setPersona('Reviewer');
    setError('');
    setEmailError('');
  };

  const handleRefresh = () => {
    loadUsers(true);
  };

  // Load users when awsConfig becomes available and user is admin
  useEffect(() => {
    if (awsConfig && isAdmin && !roleLoading) {
      loadUsers();
    }
  }, [awsConfig, isAdmin, roleLoading, loadUsers]);

  // Show loading if AWS config or role is not ready
  if (!awsConfig || roleLoading) {
    return (
      <Container>
        <Box textAlign="center" padding="xxl">
          <StatusIndicator type="loading">Loading user management...</StatusIndicator>
        </Box>
      </Container>
    );
  }

  if (!isAdmin) {
    return (
      <Container>
        <Alert type="error">Access Denied: You must be an administrator to access User Management.</Alert>
      </Container>
    );
  }

  const columnDefinitions = [
    {
      id: 'email',
      header: 'Email',
      cell: (item) => item.email,
      sortingField: 'email',
    },
    {
      id: 'persona',
      header: 'Role',
      cell: (item) => (
        <Box {...({ color: item.persona === 'Admin' ? 'text-status-info' : 'text-body-default' } as Record<string, unknown>)}>
          {item.persona}
        </Box>
      ),
      sortingField: 'persona',
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item) => <StatusIndicator type={item.status === 'active' ? 'success' : 'stopped'}>{item.status || 'active'}</StatusIndicator>,
      sortingField: 'status',
    },
    {
      id: 'createdAt',
      header: 'Created',
      cell: (item) => (item.createdAt ? new Date(item.createdAt).toLocaleDateString() : 'N/A'),
      sortingField: 'createdAt',
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (item) => (
        <Button variant="link" onClick={() => deleteUser(item.userId, item.email)} disabled={loading || refreshing}>
          Delete
        </Button>
      ),
    },
  ];

  return (
    <Container
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" onClick={handleRefresh} loading={refreshing} disabled={loading}>
                Refresh
              </Button>
              <Button variant="primary" onClick={() => setShowCreateModal(true)} disabled={loading || refreshing}>
                Create User
              </Button>
            </SpaceBetween>
          }
        >
          User Management
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert type="success" dismissible onDismiss={() => setSuccess('')}>
            {success}
          </Alert>
        )}

        <Table
          columnDefinitions={columnDefinitions}
          items={users}
          loading={loading}
          loadingText="Loading users..."
          sortingDisabled={loading || refreshing}
          empty={
            <Box textAlign="center" color="inherit">
              <Box variant="strong" textAlign="center" color="inherit">
                No users found
              </Box>
              <Box variant="p" padding={{ bottom: 's' }} textAlign="center" color="inherit">
                Create your first user to get started.
              </Box>
              <Button onClick={() => setShowCreateModal(true)}>Create User</Button>
            </Box>
          }
          header={
            <Header counter={`(${users.length})`} description="Manage users and their roles in the system">
              Users
            </Header>
          }
        />

        <Modal
          visible={showCreateModal}
          onDismiss={handleCreateModalClose}
          header="Create New User"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="link" onClick={handleCreateModalClose}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={createUser} loading={loading}>
                  Create User
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <Form>
            <SpaceBetween size="l">
              <FormField
                label="Email Address"
                errorText={emailError}
                description={
                  allowedDomains.length > 0
                    ? `Allowed domains: ${allowedDomains.join(', ')}`
                    : 'User will receive an email with temporary password'
                }
                constraintText={allowedDomains.length > 0 ? 'Email must use an allowed domain' : ''}
              >
                <Input value={email} onChange={handleEmailChange} placeholder="user@example.com" type="email" />
              </FormField>
              <FormField label="Role" description="Admin users can manage other users and configurations">
                <Select
                  selectedOption={personaOptions.find((opt) => opt.value === persona)}
                  onChange={({ detail }) => setPersona(detail.selectedOption.value)}
                  options={personaOptions}
                />
              </FormField>
            </SpaceBetween>
          </Form>
        </Modal>
      </SpaceBetween>
    </Container>
  );
};

export default UserManagementLayout;
