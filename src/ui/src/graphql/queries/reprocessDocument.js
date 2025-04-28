const reprocessDocument = /* GraphQL */ `
  mutation ReprocessDocument($objectKeys: [String!]!) {
    reprocessDocument(objectKeys: $objectKeys)
  }
`;

export default reprocessDocument;
