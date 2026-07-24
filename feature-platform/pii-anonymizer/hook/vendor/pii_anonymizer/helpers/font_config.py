# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Font configuration for consistent rendering across environments.
Forces bundled DejaVu Sans usage on both macOS and Lambda for guaranteed consistency.
"""

import os
import logging
from PIL import ImageFont

logger = logging.getLogger(__name__)


def get_consistent_font(size):
    """
    Get consistent bundled font across environments.
    Uses bundled DejaVu Sans for guaranteed consistency.
    """
    # Try bundled font first (guaranteed consistency)
    bundled_paths = [
        # Lambda layer path
        "/opt/fonts/DejaVuSans.ttf",
        # Lambda task path (in src/)
        "/var/task/src/fonts/DejaVuSans.ttf",
        # Lambda task path (root)
        "/var/task/fonts/DejaVuSans.ttf",
        # Local development path
        os.path.join(os.path.dirname(__file__), "..", "fonts", "DejaVuSans.ttf"),
    ]

    for font_path in bundled_paths:
        try:
            font = ImageFont.truetype(font_path, size)
            return font
        except (OSError, IOError) as e:
            logger.debug(f"Font not found at {font_path}: {e}")
            continue

    # Fallback to system fonts if bundled font fails
    system_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/Users/nooneyak/Library/Fonts/DejaVuSans.ttf",  # macOS user
        "/System/Library/Fonts/Arial.ttf",  # macOS Arial
        "arial.ttf",  # System Arial
    ]

    for font_path in system_paths:
        try:
            font = ImageFont.truetype(font_path, size)
            if not hasattr(get_consistent_font, "_logged"):
                logger.warning(
                    f"Using system font fallback: {font_path}, size: {size}pt"
                )
                get_consistent_font._logged = True
            return font
        except (OSError, IOError):
            continue

    # Final fallback
    if not hasattr(get_consistent_font, "_logged"):
        logger.warning(
            f"No TrueType font found, using PIL default. Tried: {bundled_paths + system_paths}"
        )
        get_consistent_font._logged = True
    return ImageFont.load_default()


def install_dejavu_macos():
    """
    Instructions for installing DejaVu Sans on macOS for consistency.
    """
    return """
    To install DejaVu Sans on macOS for consistency with Lambda:

    brew install font-dejavu

    Or download from: https://dejavu-fonts.github.io/
    """
