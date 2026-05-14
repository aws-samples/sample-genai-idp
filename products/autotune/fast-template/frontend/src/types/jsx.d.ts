// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: LicenseRef-AWS-Proprietary

import "react"

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>
    }
  }
}
