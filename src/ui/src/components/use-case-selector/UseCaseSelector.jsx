// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useEffect } from 'react';
import { Select, FormField } from '@cloudscape-design/components';
import useUseCaseContext from '../../contexts/useCase';
import { ALL_USE_CASES_ID } from '../../hooks/use-use-cases';

/* eslint-disable react/prop-types */
const UseCaseSelector = ({ isAdmin = false }) => {
  const { useCases, selectedUseCase, setSelectedUseCase, isMultiUseCaseEnabled, ALL_USE_CASES } = useUseCaseContext();

  // Clear "All Use Cases" selection when user is no longer an admin
  // (e.g., role changed during the session) to prevent unscoped data access.
  useEffect(() => {
    if (!isAdmin && selectedUseCase?.useCaseId === ALL_USE_CASES_ID) {
      setSelectedUseCase(useCases.length > 0 ? useCases[0] : null);
    }
  }, [isAdmin, selectedUseCase, setSelectedUseCase, useCases]);

  if (!isMultiUseCaseEnabled) {
    return null;
  }

  // Encode BU/UC IDs to handle slashes in identifiers
  const encodeValue = (bu, uc) => `${encodeURIComponent(bu)}/${encodeURIComponent(uc)}`;

  // Only admin users can see the "All Use Cases" option; non-admins are
  // restricted to their allowed use cases to prevent unscoped data access.
  const useCaseOptions = useCases.map((uc) => ({
    label: uc.name,
    value: encodeValue(uc.businessUnitId, uc.useCaseId),
    description: uc.description || `${uc.businessUnitId} / ${uc.useCaseId}`,
  }));

  const options = isAdmin
    ? [{ label: ALL_USE_CASES.name, value: ALL_USE_CASES_ID, description: 'View documents from all use cases' }, ...useCaseOptions]
    : useCaseOptions;

  const selectedOption = selectedUseCase
    ? options.find(
        (o) =>
          o.value ===
          (selectedUseCase.useCaseId === ALL_USE_CASES_ID
            ? ALL_USE_CASES_ID
            : encodeValue(selectedUseCase.businessUnitId, selectedUseCase.useCaseId)),
      ) || null
    : null;

  const handleChange = ({ detail }) => {
    if (detail.selectedOption.value === ALL_USE_CASES_ID) {
      setSelectedUseCase(ALL_USE_CASES);
    } else {
      const value = detail.selectedOption.value;
      // Split on the first '/' only — both parts are URI-encoded so internal slashes are safe
      const slashIdx = value.indexOf('/');
      if (slashIdx === -1) {
        setSelectedUseCase(null);
        return;
      }
      const businessUnitId = decodeURIComponent(value.substring(0, slashIdx));
      const useCaseId = decodeURIComponent(value.substring(slashIdx + 1));
      const uc = useCases.find((u) => u.businessUnitId === businessUnitId && u.useCaseId === useCaseId);
      // If not found (shouldn't happen), clear selection rather than creating partial object
      setSelectedUseCase(uc || null);
    }
  };

  return (
    <FormField label="Use Case">
      <Select
        selectedOption={selectedOption}
        onChange={handleChange}
        options={options}
        placeholder="Select a use case"
        filteringType="auto"
      />
    </FormField>
  );
};

export default UseCaseSelector;
