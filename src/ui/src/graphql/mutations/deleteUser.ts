// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const deleteUser: string = /* GraphQL */ `
  mutation DeleteUser($userId: ID!) {
    deleteUser(userId: $userId)
  }
`;

export default deleteUser;
