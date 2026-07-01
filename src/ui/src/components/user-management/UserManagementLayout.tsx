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
  Multiselect,
  StatusIndicator,
  Badge,
} from '@cloudscape-design/components';
import { generateClient } from '../../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import useUserRole from '../../hooks/use-user-role';
import useAppContext from '../../contexts/app';
import useSettingsContext from '../../contexts/settings';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import {
  listUsers,
  createUser as createUserMutation,
  deleteUser as deleteUserMutation,
  updateUser as updateUserMutation,
} from '../../graphql/generated';
import { getErrorMessage } from '../../utils/errorUtils';

const logger = new ConsoleLogger('UserManagementLayout');

interface User {
  userId: string;
  email: string;
  persona: string;
  status?: string;
  createdAt?: string;
  allowedConfigVersions?: (string | null)[] | null;
}

const UserManagementLayout = (): React.JSX.Element => {
  const { awsConfig } = useAppContext();
  const { settings } = useSettingsContext();
  const { isAdmin, loading: roleLoading } = useUserRole();
  const { versions, fetchVersions } = useConfigurationVersions();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditScopeModal, setShowEditScopeModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [email, setEmail] = useState('');
  const [persona, setPersona] = useState('Reviewer');
  const [selectedConfigVersions, setSelectedConfigVersions] = useState<readonly { label: string; value: string }[]>([]);
  const [editScopeVersions, setEditScopeVersions] = useState<readonly { label: string; value: string }[]>([]);
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
    { label: 'Admin', value: 'Admin', description: 'Full access to all operations including user management' },
    { label: 'Author', value: 'Author', description: 'Read + write access to documents, configuration, tests, discovery' },
    { label: 'Reviewer', value: 'Reviewer', description: 'HITL review operations with filtered document visibility' },
    { label: 'Viewer', value: 'Viewer', description: 'Read-only access to documents, configuration, and agent chat' },
  ];

  const configVersionOptions = useMemo(() => {
    return versions.map((v) => ({
      label: v.versionName + (v.isActive ? ' (active)' : ''),
      value: v.versionName,
    }));
  }, [versions]);

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
        const result = await client.graphql({ query: listUsers });
        const usersList =
          (((result as { data: Record<string, unknown> }).data?.listUsers as Record<string, unknown>)?.users as User[]) || [];
        logger.debug(`Loaded ${usersList.length} users`);
        setUsers(usersList);
      } catch (err) {
        logger.error('Failed to load users:', err);
        setError(`Failed to load users: ${getErrorMessage(err)}`);
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
      const allowedConfigVersions = selectedConfigVersions.length > 0 ? selectedConfigVersions.map((opt) => opt.value) : undefined;
      logger.debug('Creating user:', { email, persona, allowedConfigVersions });
      await client.graphql({
        query: createUserMutation,
        variables: { email, persona, allowedConfigVersions },
      });

      logger.debug('User created successfully');
      setSuccess(`User ${email} created successfully`);
      setShowCreateModal(false);
      setEmail('');
      setPersona('Reviewer');
      setSelectedConfigVersions([]);
      await loadUsers();
    } catch (err) {
      logger.error('Failed to create user:', err);
      setError(`Failed to create user: ${getErrorMessage(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleEditScope = (user: User) => {
    setEditingUser(user);
    // Pre-populate with current scope
    const currentScope = user.allowedConfigVersions?.filter((v): v is string => v !== null) || [];
    setEditScopeVersions(
      currentScope.map((v) => ({
        label: v,
        value: v,
      })),
    );
    setShowEditScopeModal(true);
    fetchVersions();
  };

  const saveEditScope = async () => {
    if (!editingUser || !awsConfig) return;

    setLoading(true);
    setError('');
    setSuccess('');

    try {
      const client = generateClient();
      const allowedConfigVersions = editScopeVersions.length > 0 ? editScopeVersions.map((opt) => opt.value) : null;
      logger.debug('Updating user scope:', { userId: editingUser.userId, allowedConfigVersions });
      await client.graphql({
        query: updateUserMutation,
        variables: { userId: editingUser.userId, allowedConfigVersions },
      });

      logger.debug('User scope updated successfully');
      setSuccess(`Scope updated for ${editingUser.email}`);
      setShowEditScopeModal(false);
      setEditingUser(null);
      setEditScopeVersions([]);
      await loadUsers();
    } catch (err) {
      logger.error('Failed to update user scope:', err);
      setError(`Failed to update scope: ${getErrorMessage(err)}`);
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
      setError(`Failed to delete user: ${getErrorMessage(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateModalClose = () => {
    setShowCreateModal(false);
    setEmail('');
    setPersona('Reviewer');
    setSelectedConfigVersions([]);
    setError('');
    setEmailError('');
  };

  const handleCreateModalOpen = () => {
    setShowCreateModal(true);
    fetchVersions();
  };

  const handleEditScopeModalClose = () => {
    setShowEditScopeModal(false);
    setEditingUser(null);
    setEditScopeVersions([]);
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

  const formatConfigVersions = (userVersions: (string | null)[] | null | undefined): React.ReactNode => {
    if (!userVersions || userVersions.length === 0) {
      return (
        <Box color="text-body-secondary">
          <em>All versions</em>
        </Box>
      );
    }
    const validVersions = userVersions.filter((v): v is string => v !== null);
    return (
      <SpaceBetween direction="horizontal" size="xxs">
        {validVersions.map((v) => (
          <Badge key={v} color="blue">
            {v}
          </Badge>
        ))}
      </SpaceBetween>
    );
  };

  const columnDefinitions = [
    {
      id: 'email',
      header: 'Email',
      cell: (item: User) => item.email,
      sortingField: 'email',
    },
    {
      id: 'persona',
      header: 'Role',
      cell: (item: User) => {
        const colorMap: Record<string, string> = {
          Admin: 'text-status-info',
          Author: 'text-status-success',
          Reviewer: 'text-body-default',
          Viewer: 'text-body-secondary',
        };
        return <Box {...({ color: colorMap[item.persona] || 'text-body-default' } as Record<string, unknown>)}>{item.persona}</Box>;
      },
      sortingField: 'persona',
    },
    {
      id: 'allowedConfigVersions',
      header: 'Config Version Scope',
      cell: (item: User) => formatConfigVersions(item.allowedConfigVersions),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: User) => (
        <StatusIndicator type={item.status === 'active' ? 'success' : 'stopped'}>{item.status || 'active'}</StatusIndicator>
      ),
      sortingField: 'status',
    },
    {
      id: 'createdAt',
      header: 'Created',
      cell: (item: User) => (item.createdAt ? new Date(item.createdAt).toLocaleDateString() : 'N/A'),
      sortingField: 'createdAt',
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (item: User) => (
        <SpaceBetween direction="horizontal" size="xs">
          {item.persona !== 'Admin' && (
            <Button variant="link" onClick={() => handleEditScope(item)} disabled={loading || refreshing}>
              Edit scope
            </Button>
          )}
          <Button variant="link" onClick={() => deleteUser(item.userId, item.email)} disabled={loading || refreshing}>
            Delete
          </Button>
        </SpaceBetween>
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
              <Button variant="primary" onClick={handleCreateModalOpen} disabled={loading || refreshing}>
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
              <Button onClick={handleCreateModalOpen}>Create User</Button>
            </Box>
          }
          header={
            <Header counter={`(${users.length})`} description="Manage users and their roles in the system">
              Users
            </Header>
          }
        />

        {/* Create User Modal */}
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
              <FormField label="Role" description="Select the role that defines what this user can access and modify">
                <Select
                  selectedOption={personaOptions.find((opt) => opt.value === persona) ?? null}
                  onChange={({ detail }) => setPersona(detail.selectedOption.value ?? '')}
                  options={personaOptions}
                />
              </FormField>
              <FormField
                label={
                  <span>
                    Configuration Version Scope <em>- optional</em>
                  </span>
                }
                description="Restrict this user to specific configuration versions. Leave empty for unrestricted access to all versions."
              >
                <Multiselect
                  selectedOptions={selectedConfigVersions}
                  onChange={({ detail }) => setSelectedConfigVersions(detail.selectedOptions as { label: string; value: string }[])}
                  options={configVersionOptions}
                  placeholder="All versions (unrestricted)"
                  filteringType="auto"
                  tokenLimit={3}
                />
              </FormField>
            </SpaceBetween>
          </Form>
        </Modal>

        {/* Edit Scope Modal */}
        <Modal
          visible={showEditScopeModal}
          onDismiss={handleEditScopeModalClose}
          header={`Edit Config Version Scope — ${editingUser?.email ?? ''}`}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="link" onClick={handleEditScopeModalClose}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={saveEditScope} loading={loading}>
                  Save Scope
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <Form>
            <SpaceBetween size="l">
              <FormField
                label="Configuration Version Scope"
                description="Select which configuration versions this user can access. Clear all to give unrestricted access."
              >
                <Multiselect
                  selectedOptions={editScopeVersions}
                  onChange={({ detail }) => setEditScopeVersions(detail.selectedOptions as { label: string; value: string }[])}
                  options={configVersionOptions}
                  placeholder="All versions (unrestricted)"
                  filteringType="auto"
                  tokenLimit={3}
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
