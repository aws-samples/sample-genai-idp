# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Config-shape migrations.

Each migration is a pure ``dict -> dict`` transform that upgrades a stored
configuration from one ``config_format_version`` to the next. Migrations are
idempotent so they can be safely applied on every read (see
``IDPConfig.log_deprecated_fields`` and ``ConfigurationManager``).
"""

from .v05_to_v06 import migrate_v05_to_v06

__all__ = ["migrate_v05_to_v06"]
