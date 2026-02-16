// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const handlePrint = (): void => {
  const printStyles = `
    @media print {
      /* Hide all possible sidebar elements */
      .awsui-app-layout-navigation,
      .awsui-side-navigation,
      .awsui-app-layout-tools,
      nav, aside,
      [data-testid="app-layout-navigation"],
      [data-testid="side-navigation"] {
        display: none !important;
      }
      
      /* Full width for main content */
      .awsui-app-layout-main,
      .awsui-app-layout-content {
        width: 100% !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
      }
      
      /* Remove height constraints that limit to 1 page */
      .awsui-container,
      .awsui-space-between {
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
      }
      
      /* Allow page breaks */
      .awsui-container {
        page-break-inside: auto !important;
      }
      
      /* Make tables print fully */
      .awsui-table-container {
        overflow: visible !important;
        max-height: none !important;
        height: auto !important;
      }
    }
  `;

  const styleElement = document.createElement('style');
  styleElement.innerHTML = printStyles;
  document.head.appendChild(styleElement);

  window.print();

  document.head.removeChild(styleElement);
};

export default handlePrint;
