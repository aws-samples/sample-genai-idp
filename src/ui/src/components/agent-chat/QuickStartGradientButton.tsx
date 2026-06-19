// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import './QuickStartGradientButton.css';

interface QuickStartGradientButtonProps {
  onClick: () => void;
  label?: string;
}

const QuickStartGradientButton = ({ onClick, label = 'Quick Start' }: QuickStartGradientButtonProps): React.JSX.Element => (
  <button type="button" className="quick-start-gradient-button" onClick={onClick}>
    <span aria-hidden="true" className="quick-start-gradient-button-icon">
      ✨
    </span>
    {label}
  </button>
);

export default QuickStartGradientButton;
