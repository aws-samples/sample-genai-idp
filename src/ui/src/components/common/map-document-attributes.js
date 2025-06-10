// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getDocumentConfidenceAlertCount } from './confidence-alerts-utils';

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
      ListPK: listPK,
      ListSK: listSK,
    } = item;

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

    const mapping = {
      objectKey,
      objectStatus,
      initialEventTime: formatDate(initialEventTime),
      queuedTime: formatDate(queuedTime),
      workflowStartTime: formatDate(workflowStartTime),
      completionTime: formatDate(completionTime),
      workflowExecutionArn,
      workflowStatus,
      duration: getDuration(completionTime, initialEventTime),
      sections,
      pages,
      pageCount,
      metering,
      evaluationReportUri,
      evaluationStatus,
      summaryReportUri,
      confidenceAlertCount,
      listPK,
      listSK,
    };

    console.log('mapped-document-attributes', mapping);

    return mapping;
  });
};

export default mapDocumentsAttributes;
