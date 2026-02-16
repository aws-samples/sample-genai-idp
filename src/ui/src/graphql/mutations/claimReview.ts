// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const claimReview: string = /* GraphQL */ `
  mutation ClaimReview($objectKey: String!) {
    claimReview(objectKey: $objectKey) {
      ObjectKey
      ObjectStatus
      HITLStatus
      HITLReviewOwner
      HITLReviewOwnerEmail
    }
  }
`;

export default claimReview;
