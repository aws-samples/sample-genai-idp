const deleteDocument = /* GraphQL */ `
  mutation DeleteDocument($objectKeys: [String!]!) {
    deleteDocument(objectKeys: $objectKeys)
  }
`;

export default deleteDocument;
