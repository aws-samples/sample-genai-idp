// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Utility functions for handling confidence threshold alerts
 */

/**
 * Calculate the total count of confidence threshold alerts for a document
 * @param {Array} sections - Array of document sections
 * @returns {number} Total count of confidence threshold alerts
 */
export const getDocumentConfidenceAlertCount = (sections) => {
  if (!sections || !Array.isArray(sections)) {
    return 0;
  }

  return sections.reduce((total, section) => {
    if (section.ConfidenceThresholdAlerts && Array.isArray(section.ConfidenceThresholdAlerts)) {
      return total + section.ConfidenceThresholdAlerts.length;
    }
    return total;
  }, 0);
};

/**
 * Calculate the count of confidence threshold alerts for a specific section
 * @param {Object} section - Document section
 * @returns {number} Count of confidence threshold alerts for the section
 */
export const getSectionConfidenceAlertCount = (section) => {
  if (!section || !section.ConfidenceThresholdAlerts || !Array.isArray(section.ConfidenceThresholdAlerts)) {
    return 0;
  }
  return section.ConfidenceThresholdAlerts.length;
};

/**
 * Check if a field should be highlighted due to low confidence
 * @param {string} fieldName - Name of the field
 * @param {number} fieldConfidence - Confidence value for the field
 * @param {Array} confidenceThresholdAlerts - Array of confidence threshold alerts
 * @returns {Object} Object with highlight flag and threshold info
 */
export const getFieldHighlightInfo = (fieldName, fieldConfidence, confidenceThresholdAlerts) => {
  if (!confidenceThresholdAlerts || !Array.isArray(confidenceThresholdAlerts) || !fieldName) {
    return { shouldHighlight: false };
  }

  const alertMatch = confidenceThresholdAlerts.find((alert) => alert.attributeName === fieldName);

  if (alertMatch) {
    return {
      shouldHighlight: true,
      confidence: alertMatch.confidence,
      confidenceThreshold: alertMatch.confidenceThreshold,
      alert: alertMatch,
    };
  }

  return { shouldHighlight: false };
};

/**
 * Get confidence information for a field from explainability data
 * @param {string} fieldName - Name of the field
 * @param {Object} explainabilityInfo - Explainability info object containing confidence data for all fields
 * @returns {Object} Object with confidence info and display properties
 */
export const getFieldConfidenceInfo = (fieldName, explainabilityInfo) => {
  if (!explainabilityInfo || !fieldName) {
    return { hasConfidenceInfo: false };
  }

  // explainabilityInfo is typically an array, get the first element
  const explainabilityData = Array.isArray(explainabilityInfo) ? explainabilityInfo[0] : explainabilityInfo;

  if (!explainabilityData || typeof explainabilityData !== 'object') {
    return { hasConfidenceInfo: false };
  }

  const fieldData = explainabilityData[fieldName];
  if (!fieldData || typeof fieldData !== 'object') {
    return { hasConfidenceInfo: false };
  }

  const { confidence } = fieldData;
  const confidenceThreshold = fieldData.confidence_threshold;

  if (typeof confidence !== 'number' || typeof confidenceThreshold !== 'number') {
    return { hasConfidenceInfo: false };
  }

  const isAboveThreshold = confidence >= confidenceThreshold;

  return {
    hasConfidenceInfo: true,
    confidence,
    confidenceThreshold,
    isAboveThreshold,
    shouldHighlight: !isAboveThreshold,
    textColor: isAboveThreshold ? '#16794d' : '#d13313', // Green for good, red for poor
  };
};

/**
 * Get all confidence threshold alerts for a section as a map by attribute name
 * @param {Object} section - Document section
 * @returns {Object} Map of attribute names to alert objects
 */
export const getConfidenceAlertsMap = (section) => {
  if (!section || !section.ConfidenceThresholdAlerts || !Array.isArray(section.ConfidenceThresholdAlerts)) {
    return {};
  }

  const alertsMap = {};
  section.ConfidenceThresholdAlerts.forEach((alert) => {
    if (alert.attributeName) {
      alertsMap[alert.attributeName] = alert;
    }
  });

  return alertsMap;
};
