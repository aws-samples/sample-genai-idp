import React, { useState, useEffect } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Button,
  Alert,
  Spinner,
  Form,
  FormField,
  Input,
  Textarea,
  Toggle,
  Select,
  Badge,
} from '@awsui/components-react';
import useConfiguration from '../../hooks/use-configuration';

const ConfigurationLayout = () => {
  const {
    schema,
    defaultConfig,
    mergedConfig,
    loading,
    error,
    updateConfiguration,
    resetToDefault,
    isCustomized,
    fetchConfiguration,
  } = useConfiguration();

  const [formValues, setFormValues] = useState({});
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);

  // Initialize form values from merged config
  useEffect(() => {
    if (mergedConfig) {
      console.log('Setting form values from mergedConfig:', mergedConfig);
      setFormValues(mergedConfig);
    }
  }, [mergedConfig]);

  if (loading) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
          <Box padding="s">Loading configuration...</Box>
        </Box>
      </Container>
    );
  }

  if (error) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Alert type="error" header="Error loading configuration">
          {error}
          <Button onClick={fetchConfiguration} variant="primary" style={{ marginTop: '1rem' }}>
            Retry
          </Button>
        </Alert>
      </Container>
    );
  }

  if (!schema || !mergedConfig) {
    return (
      <Container header={<Header variant="h2">Configuration</Header>}>
        <Alert type="error" header="Configuration not available">
          Unable to load configuration schema or values.
          <Button onClick={fetchConfiguration} variant="primary" style={{ marginTop: '1rem' }}>
            Retry
          </Button>
        </Alert>
      </Container>
    );
  }

  const handleInputChange = (path, value) => {
    console.log(`Updating path ${path} with value:`, value);

    // Deep clone current form values
    const newFormValues = JSON.parse(JSON.stringify(formValues));

    // Navigate to the correct path and update the value
    const pathSegments = path.split('.');
    let current = newFormValues;

    pathSegments.slice(0, -1).forEach((segment) => {
      if (!Object.hasOwn(current, segment) || !current[segment]) {
        current[segment] = {};
      }
      current = current[segment];
    });

    current[pathSegments[pathSegments.length - 1]] = value;
    console.log('New form values:', newFormValues);
    setFormValues(newFormValues);
  };

  const handleResetToDefault = async (path) => {
    // Get the default value at this path
    const pathSegments = path.split('.');
    const defaultValue = pathSegments.reduce((acc, segment) => {
      return acc && acc[segment] !== undefined ? acc[segment] : undefined;
    }, defaultConfig);

    console.log(`Resetting ${path} to default value:`, defaultValue);

    // Update form value to default
    handleInputChange(path, defaultValue);

    // Reset in custom config
    await resetToDefault(path);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);

    try {
      // Find differences between form values and default config
      const findDifferences = (formObj, defaultObj, currentPath = '', result = {}) => {
        // Make sure we go through all keys in the form values
        Object.keys(formObj)
          .filter((key) => Object.hasOwn(formObj, key))
          .forEach((key) => {
            const newPath = currentPath ? `${currentPath}.${key}` : key;

            if (
              typeof formObj[key] === 'object' &&
              formObj[key] !== null &&
              !Array.isArray(formObj[key]) &&
              defaultObj &&
              typeof defaultObj[key] === 'object' &&
              defaultObj[key] !== null
            ) {
              // Recurse for nested objects
              findDifferences(formObj[key], defaultObj[key], newPath, result);
            } else if (
              defaultObj === undefined ||
              defaultObj[key] === undefined ||
              JSON.stringify(formObj[key]) !== JSON.stringify(defaultObj[key])
            ) {
              // Set value at path in result
              let resultCurrent = result;
              const segments = newPath.split('.');

              segments.slice(0, -1).forEach((segment) => {
                if (!Object.hasOwn(resultCurrent, segment) || !resultCurrent[segment]) {
                  resultCurrent[segment] = {};
                }
                resultCurrent = resultCurrent[segment];
              });

              resultCurrent[segments[segments.length - 1]] = formObj[key];
            }
          });

        return result;
      };

      // Get the differences between form values and default config
      const updatedCustom = findDifferences(formValues, defaultConfig);

      // Log the changes that will be saved
      console.log('Saving custom config:', updatedCustom);

      if (Object.keys(updatedCustom).length === 0) {
        // No changes to save - all values are at default
        setSaveSuccess(true);
        return;
      }

      // Save to backend
      const success = await updateConfiguration(updatedCustom);

      if (success) {
        setSaveSuccess(true);
        // Force a refresh of the configuration to ensure UI is in sync with backend
        setTimeout(() => {
          fetchConfiguration();
        }, 1000);
      } else {
        setSaveError('Failed to save configuration. Please try again.');
      }
    } catch (err) {
      console.error('Save error:', err);
      setSaveError(`Error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Helper function to get value from formValues
  const getValueAtPath = (path) => {
    const segments = path.split('.');
    return segments.reduce((acc, segment) => {
      if (acc === undefined || acc === null) {
        return undefined;
      }
      return acc[segment];
    }, formValues);
  };

  // Helper function to render a specific field based on its type
  const renderField = (key, property, currentValue, isCustomValue, fullPath) => {
    console.log(`Rendering field: ${fullPath}, type: ${property.type}, value:`, currentValue);

    let inputField;

    if (property.type === 'string') {
      // Check if we should use textarea for long strings like prompts
      if (property.format === 'text-area' || fullPath.toLowerCase().includes('prompt')) {
        inputField = (
          <Textarea
            rows={8}
            value={currentValue !== undefined ? currentValue : ''}
            onChange={({ detail }) => handleInputChange(fullPath, detail.value)}
            style={{ width: '100%' }}
          />
        );
      } else if (property.enum) {
        // For enum values, use Select
        const options = property.enum.map((value) => ({ value, label: value }));
        inputField = (
          <Select
            options={options}
            selectedOption={{ value: currentValue, label: currentValue }}
            onChange={({ detail }) => handleInputChange(fullPath, detail.selectedOption.value)}
            expandToViewport
            style={{ width: '100%' }}
          />
        );
      } else {
        inputField = (
          <Input
            value={currentValue !== undefined ? currentValue : ''}
            onChange={({ detail }) => handleInputChange(fullPath, detail.value)}
            style={{ width: '100%' }}
          />
        );
      }
    } else if (property.type === 'number' || property.type === 'integer') {
      inputField = (
        <Input
          type="number"
          step={property.type === 'number' ? '0.1' : '1'}
          value={currentValue !== undefined ? currentValue : ''}
          onChange={({ detail }) => {
            const numValue = property.type === 'number' ? parseFloat(detail.value) : parseInt(detail.value, 10);
            handleInputChange(fullPath, numValue);
          }}
          style={{ width: '100%' }}
        />
      );
    } else if (property.type === 'boolean') {
      inputField = (
        <Toggle checked={!!currentValue} onChange={({ detail }) => handleInputChange(fullPath, detail.checked)} />
      );
    } else {
      // Default to text input
      inputField = (
        <Input
          value={currentValue !== undefined ? currentValue : ''}
          onChange={({ detail }) => handleInputChange(fullPath, detail.value)}
          style={{ width: '100%' }}
        />
      );
    }

    // Create constraint text
    let constraintText;
    if (property.minimum !== undefined || property.maximum !== undefined) {
      const minText = property.minimum !== undefined ? `Min: ${property.minimum}` : '';
      const maxText = property.maximum !== undefined ? `Max: ${property.maximum}` : '';

      if (minText && maxText) {
        constraintText = `${minText}, ${maxText}`;
      } else {
        constraintText = minText || maxText;
      }
    }

    return (
      <FormField
        key={key}
        label={
          <span>
            {property.title || fullPath.split('.').pop()} {/* Added space here */}
            {isCustomValue && (
              <Badge color="blue" style={{ marginLeft: '10px' }}>
                Custom
              </Badge>
            )}
          </span>
        }
        description={property.description}
        constraintText={constraintText}
        stretch
        style={{ width: '100%' }}
      >
        <div style={{ display: 'flex', width: '100%' }}>
          <div style={{ flexGrow: 1 }}>{inputField}</div>
          {isCustomValue && (
            <div style={{ marginLeft: '10px', flexShrink: 0 }}>
              <Button variant="link" onClick={() => handleResetToDefault(fullPath)}>
                Reset to default
              </Button>
            </div>
          )}
        </div>
      </FormField>
    );
  };

  // Helper function to render properties from schema
  const renderSchemaProperties = (properties) => {
    return Object.entries(properties).map(([topLevelKey, topLevelProperty]) => {
      // For top level properties
      if (topLevelProperty.type !== 'object') {
        const path = topLevelKey;
        const value = getValueAtPath(path);
        const customized = isCustomized(path);

        return renderField(`${path}`, topLevelProperty, value, customized, path);
      }

      // For object properties (like "extraction")
      return (
        <Box key={`${topLevelKey}`} padding={{ bottom: 'm' }}>
          <Header variant="h3">
            {topLevelProperty.title || topLevelKey}
            {topLevelProperty.description && (
              <Box padding={{ top: 'xxs' }} color="text-body-secondary" fontSize="body-s">
                {topLevelProperty.description}
              </Box>
            )}
          </Header>

          {topLevelProperty.properties && (
            <SpaceBetween size="m">
              {Object.entries(topLevelProperty.properties).map(([childKey, childProperty]) => {
                const fullPath = `${topLevelKey}.${childKey}`;
                const value = getValueAtPath(fullPath);
                const customized = isCustomized(fullPath);

                return renderField(`${fullPath}`, childProperty, value, customized, fullPath);
              })}
            </SpaceBetween>
          )}
        </Box>
      );
    });
  };

  // Render form fields function
  const renderFormFields = () => {
    // Check if schema is actually a string disguised as an object
    if (typeof schema === 'string') {
      try {
        // Try to parse it directly
        const parsedSchema = JSON.parse(schema);
        console.log('Successfully parsed schema string:', parsedSchema);

        // If it parses successfully, use it instead of the original schema
        if (parsedSchema && parsedSchema.properties) {
          return renderSchemaProperties(parsedSchema.properties);
        }
      } catch (e) {
        console.error('Failed to parse schema string:', e);
      }
    }

    // Check if schema is missing properties
    if (!schema || !schema.properties) {
      console.error('Schema or schema.properties is undefined:', schema);
      return (
        <Alert type="error" header="Schema Error">
          <p>Invalid schema structure. Properties not found.</p>
          <p>Schema type: {typeof schema}</p>
          <pre>{JSON.stringify(schema, null, 2)}</pre>

          {typeof schema === 'string' && (
            <div>
              <p>Attempting to parse the string...</p>
              <Button
                onClick={() => {
                  try {
                    const parsed = JSON.parse(schema);
                    console.log('Manual parse result:', parsed);
                    alert('Schema parsed successfully! See console for details.');
                  } catch (e) {
                    console.error('Manual parse failed:', e);
                    alert(`Parse failed: ${e.message}`);
                  }
                }}
              >
                Try Parse Manually
              </Button>
            </div>
          )}
        </Alert>
      );
    }

    return renderSchemaProperties(schema.properties);
  };

  return (
    <Container header={<Header variant="h2">Configuration</Header>}>
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="primary" onClick={handleSave} loading={isSaving}>
              Save changes
            </Button>
          </SpaceBetween>
        }
      >
        {saveSuccess && (
          <Alert
            type="success"
            dismissible
            onDismiss={() => setSaveSuccess(false)}
            header="Configuration saved successfully"
          >
            Your configuration changes have been saved.
          </Alert>
        )}

        {saveError && (
          <Alert type="error" dismissible onDismiss={() => setSaveError(null)} header="Error saving configuration">
            {saveError}
          </Alert>
        )}

        <SpaceBetween size="l">{renderFormFields()}</SpaceBetween>
      </Form>
    </Container>
  );
};

export default ConfigurationLayout;
