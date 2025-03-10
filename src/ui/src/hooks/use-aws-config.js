// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useEffect } from 'react';
import { Amplify } from 'aws-amplify';
import awsExports from '../aws-exports';

const useAwsConfig = () => {
  const [awsConfig, setAwsConfig] = useState();
  useEffect(() => {
    Amplify.configure(awsExports);
    setAwsConfig(awsExports);
  }, [awsExports]);
  return awsConfig;
};

export default useAwsConfig;
