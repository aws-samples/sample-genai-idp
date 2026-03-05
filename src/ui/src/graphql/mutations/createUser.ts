// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const createUser: string = /* GraphQL */ `
  mutation CreateUser($email: String!, $persona: String!, $allowedUseCases: [String]) {
    createUser(email: $email, persona: $persona, allowedUseCases: $allowedUseCases) {
      userId
      email
      persona
      status
      createdAt
      allowedUseCases
    }
  }
`;

export default createUser;
