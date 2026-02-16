// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const completeSectionReview: string = /* GraphQL */ `
  mutation CompleteSectionReview($objectKey: String!, $sectionId: String!, $editedData: AWSJSON) {
    completeSectionReview(objectKey: $objectKey, sectionId: $sectionId, editedData: $editedData) {
      ObjectKey
      ObjectStatus
      HITLStatus
      HITLSectionsPending
      HITLSectionsCompleted
      HITLSectionsSkipped
      HITLReviewHistory
    }
  }
`;

export default completeSectionReview;
