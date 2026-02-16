const GET_TEST_RUNS: string = `
  query GetTestRuns($timePeriodHours: Int, $startDateTime: AWSDateTime, $endDateTime: AWSDateTime) {
    getTestRuns(timePeriodHours: $timePeriodHours, startDateTime: $startDateTime, endDateTime: $endDateTime) {
      testRunId
      testSetId
      testSetName
      status
      filesCount
      createdAt
      completedAt
      context
      configVersion
    }
  }
`;

export default GET_TEST_RUNS;
