// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const skipAllSectionsReview: string = /* GraphQL */ `
  mutation SkipAllSectionsReview($objectKey: String!) {
    skipAllSectionsReview(objectKey: $objectKey) {
      ObjectKey
      ObjectStatus
      HITLStatus
      HITLTriggered
      HITLCompleted
      HITLSectionsPending
      HITLSectionsCompleted
      HITLSectionsSkipped
      HITLReviewOwner
      HITLReviewOwnerEmail
      HITLReviewHistory
    }
  }
`;

export default skipAllSectionsReview;
