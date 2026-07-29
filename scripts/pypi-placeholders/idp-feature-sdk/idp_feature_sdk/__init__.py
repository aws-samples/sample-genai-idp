# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Reserved-name placeholder for ``idp-feature-sdk`` — NOT the real package.

This distribution exists only to hold the name ``idp-feature-sdk`` on public
PyPI, so it cannot be registered by someone else and used to attack builds of
the GenAI IDP Accelerator via dependency confusion.

The real ``idp_feature_sdk`` is first-party: it lives in the accelerator repo at
``lib/idp_feature_sdk`` and is installed from a local checkout, never from PyPI.

Importing this placeholder raises immediately and says why. That is deliberate:
a stub that imports quietly but exports nothing produces confusing errors far
from their cause, which is precisely the failure mode this package prevents.
"""

_MESSAGE = """\
idp-feature-sdk from PyPI is a NAME PLACEHOLDER, not a functional package.

You have installed a reserved-name stub published by AWS to prevent dependency
confusion. It contains no code.

The real idp_feature_sdk is part of the GenAI IDP Accelerator and is installed
from a local checkout of that repository, not from PyPI:

    git clone https://github.com/aws-solutions-library-samples/\
accelerated-intelligent-document-processing-on-aws
    cd accelerated-intelligent-document-processing-on-aws
    make setup          # installs all first-party packages together

If you reached this error while building the accelerator, a bare requirement was
resolved from PyPI instead of the local checkout. Diagnose with:

    python scripts/check_first_party_deps.py
"""

raise RuntimeError(_MESSAGE)
