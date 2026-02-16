// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const listUsers: string = /* GraphQL */ `
  query ListUsers {
    listUsers {
      users {
        userId
        email
        persona
        status
        createdAt
      }
    }
  }
`;

export default listUsers;
