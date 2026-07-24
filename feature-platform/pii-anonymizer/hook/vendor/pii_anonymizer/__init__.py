# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored subset of AWS Labs pii-anonymizer (see ../PROVENANCE.md).
# The upstream src/__init__.py eagerly re-exported the whole package (incl.
# infra/, log_scrubber, core.redactor) which we intentionally did NOT vendor.
# The vendored submodules import each other with ABSOLUTE names rooted here
# (`from core...`, `from helpers...`), so this directory is placed on sys.path
# and imported as top-level packages — this package root re-export is not used.
# Kept intentionally empty to avoid pulling in un-vendored modules.
