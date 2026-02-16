// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Debug utilities for troubleshooting confidence alerts
 */

/**
 * Log section structure for debugging confidence alerts
 * @param {Object} section - Document section
 * @param {string} sectionId - Section identifier for logging
 */
export const debugSectionStructure = (section: Record<string, unknown>, sectionId: string = 'Unknown'): void => {
  if (typeof console !== 'undefined' && console.log) {
    console.log(`=== Section ${sectionId} Debug Info ===`);
    console.log('Section keys:', Object.keys(section));
    console.log('Has explainabilityData:', !!section.explainabilityData);
    console.log('Has Output:', !!section.Output);

    if (section.Output) {
      console.log('Output keys:', Object.keys(section.Output));

      // Check for confidence-related data in Output
      Object.keys(section.Output).forEach((key) => {
        const value = section.Output[key];
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const hasConfidenceFields = Object.values(value).some(
            (fieldValue) =>
              fieldValue && typeof fieldValue === 'object' && typeof (fieldValue as Record<string, unknown>).confidence === 'number',
          );

          if (hasConfidenceFields) {
            console.log(`Found confidence data in Output.${key}:`, value); // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring - Data from trusted internal source only
          }
        }
      });
    }

    console.log('Has ConfidenceThresholdAlerts:', !!section.ConfidenceThresholdAlerts);
    if (section.ConfidenceThresholdAlerts) {
      console.log('ConfidenceThresholdAlerts count:', (section.ConfidenceThresholdAlerts as unknown[]).length);
      console.log('ConfidenceThresholdAlerts:', section.ConfidenceThresholdAlerts);
    }

    console.log('=== End Section Debug ===');
  }
};

/**
 * Log document structure for debugging
 * @param {Object} document - Document object
 */
export const debugDocumentStructure = (document: Record<string, unknown>): void => {
  if (typeof console !== 'undefined' && console.log) {
    console.log('=== Document Debug Info ===');
    console.log('Document keys:', Object.keys(document));
    console.log('Has sections:', !!document.sections);
    console.log('Has mergedConfig:', !!document.mergedConfig);

    if (document.sections && Array.isArray(document.sections)) {
      console.log('Sections count:', document.sections.length);
      document.sections.forEach((section, index) => {
        debugSectionStructure(section, section.Id || `Section ${index + 1}`);
      });
    }

    if (document.mergedConfig && (document.mergedConfig as Record<string, unknown>).assessment) {
      console.log(
        'Default confidence threshold from config:',
        ((document.mergedConfig as Record<string, unknown>).assessment as Record<string, unknown>).default_confidence_threshold,
      );
    }

    console.log('=== End Document Debug ===');
  }
};
