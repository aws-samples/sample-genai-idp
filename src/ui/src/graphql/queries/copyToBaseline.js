const copyToBaseline = /* GraphQL */ `
  mutation CopyToBaseline($objectKey: String!) {
    copyToBaseline(objectKey: $objectKey) {
      success
      message
    }
  }
`;

export default copyToBaseline;
