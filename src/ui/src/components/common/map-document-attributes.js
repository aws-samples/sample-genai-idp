// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getDocumentConfidenceAlertCount } from './confidence-alerts-utils';

// Helper function to determine Review Status without nested ternaries
const getHitlStatus = (status) => {
  if (!status || status === 'N/A') {
    return 'N/A';
  }
  return status;
};

// Helper function to check if HITL is completed (includes skipped as review is done)
const isHitlCompleted = (status) => {
  if (!status) return false;
  const statusLower = status.toLowerCase();
  return statusLower === 'completed' || statusLower === 'skipped' || statusLower.includes('complete') || statusLower.includes('skipped');
};

/* Maps document attributes from API to a format that can be used in tables and panel */
// eslint-disable-next-line arrow-body-style
const mapDocumentsAttributes = (documents) => {
  return documents.map((item) => {
    const {
      ObjectKey: objectKey,
      ObjectStatus: objectStatus,
      InitialEventTime: initialEventTime,
      QueuedTime: queuedTime,
      WorkflowStartTime: workflowStartTime,
      CompletionTime: completionTime,
      WorkflowExecutionArn: workflowExecutionArn,
      WorkflowStatus: workflowStatus,
      Sections: sections,
      Pages: pages,
      PageCount: pageCount,
      Metering: meteringJson,
      EvaluationReportUri: evaluationReportUri,
      EvaluationStatus: evaluationStatus,
      SummaryReportUri: summaryReportUri,
      RuleValidationResultUri: ruleValidationResultUri,
      ListPK: listPK,
      ListSK: listSK,
      HITLStatus: hitlStatus,
      HITLReviewURL: hitlReviewURL,
      ConfigVersion: configVersion,
    } = item;

    // Extract HITL sections arrays
    const hitlSectionsPending = item.HITLSectionsPending || [];
    const hitlSectionsCompleted = item.HITLSectionsCompleted || [];
    const hitlSectionsSkipped = item.HITLSectionsSkipped || [];
    const hitlReviewOwner = item.HITLReviewOwner || '';
    const hitlReviewOwnerEmail = item.HITLReviewOwnerEmail || '';
    const hitlReviewedBy = item.HITLReviewedBy || '';
    const hitlReviewedByEmail = item.HITLReviewedByEmail || '';
    // HITLReviewHistory comes as AWSJSON (string), parse if needed
    let hitlReviewHistory = item.HITLReviewHistory || [];
    if (typeof hitlReviewHistory === 'string') {
      try {
        hitlReviewHistory = JSON.parse(hitlReviewHistory);
      } catch (e) {
        hitlReviewHistory = [];
      }
    }

    const formatDate = (timestamp) => {
      return timestamp && timestamp !== '0' ? new Date(timestamp).toISOString() : '';
    };

    const getDuration = (end, start) => {
      if (!end || end === '0' || !start || start === '0') return '';
      const duration = new Date(end) - new Date(start);
      return `${Math.floor(duration / 60000)}:${String(Math.floor((duration / 1000) % 60)).padStart(2, '0')}`;
    };

    // Parse metering data if available
    let metering = null;
    if (meteringJson) {
      try {
        metering = JSON.parse(meteringJson);
      } catch (error) {
        console.error('Error parsing metering data:', error);
      }
    }

    // Calculate confidence alert count
    const confidenceAlertCount = getDocumentConfidenceAlertCount(sections);

    // Extract HITL metadata - use HITLTriggered from backend, fallback to status check
    const hitlTriggered = item.HITLTriggered === true || (hitlStatus && hitlStatus !== 'N/A');
    const hitlCompleted = isHitlCompleted(hitlStatus);

    // Create a unique ID combining PK and SK for proper row tracking
    const uniqueId = listPK && listSK ? `${listPK}#${listSK}` : objectKey;

    const mapping = {
      uniqueId,
      objectKey,
      objectStatus,
      initialEventTime: formatDate(initialEventTime),
      queuedTime: formatDate(queuedTime),
      workflowStartTime: formatDate(workflowStartTime),
      completionTime: formatDate(completionTime),
      workflowExecutionArn,
      executionArn: workflowExecutionArn, // Add executionArn for Step Functions flow viewer
      workflowStatus,
      duration: getDuration(completionTime, initialEventTime),
      sections,
      pages:
        pages?.map((page) => ({
          ...page,
          TextConfidenceUri: page.TextConfidenceUri || null,
        })) || [],
      pageCount,
      metering,
      evaluationReportUri,
      evaluationStatus,
      summaryReportUri,
      ruleValidationResultUri,
      confidenceAlertCount,
      listPK,
      listSK,
      hitlTriggered,
      hitlReviewURL,
      hitlCompleted,
      hitlStatus: getHitlStatus(hitlStatus),
      hitlSectionsPending,
      hitlSectionsCompleted,
      hitlSectionsSkipped,
      hitlReviewOwner,
      hitlReviewOwnerEmail,
      hitlReviewedBy,
      hitlReviewedByEmail,
      hitlReviewHistory,
      configVersion,
    };

    console.log('mapped-document-attributes', mapping);

    return mapping;
  });
};

export default mapDocumentsAttributes;
