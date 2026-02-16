// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const releaseReview: string = /* GraphQL */ `
  mutation ReleaseReview($objectKey: String!) {
    releaseReview(objectKey: $objectKey) {
      ObjectKey
      ObjectStatus
      HITLStatus
      HITLReviewOwner
      HITLReviewOwnerEmail
    }
  }
`;

export default releaseReview;
