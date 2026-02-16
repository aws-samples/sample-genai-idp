// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const createUser: string = /* GraphQL */ `
  mutation CreateUser($email: String!, $persona: String!) {
    createUser(email: $email, persona: $persona) {
      userId
      email
      persona
      status
      createdAt
    }
  }
`;

export default createUser;
