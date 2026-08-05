# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Custom SAM build (Metadata.BuildMethod: makefile). Copies this package's
# sources into the SAM artifacts dir and installs its requirements.
#
# Install for the Lambda x86_64 Linux runtime, NOT the build host. These
# requirements include packages with compiled extensions (e.g. pyarrow,
# Pillow); a plain `pip install -t` on an ARM/Mac build host ships a darwin
# .so that cannot load on Lambda. Cross-target manylinux wheels only, matching
# the layer build in idp_sdk publish and the chat_stream_processor precedent.
#
# NOTE: --only-binary=:all: means a dependency that publishes no matching
# manylinux wheel fails the build here rather than at runtime. If you add a
# sdist-only dependency, either vendor a wheel or drop the flag for it.

build-FccDatasetDeployerFunction:
	mkdir -p $(ARTIFACTS_DIR)
	cp $(CURDIR)/*.py $(ARTIFACTS_DIR)/
	python -m pip install -r $(CURDIR)/requirements.txt -t $(ARTIFACTS_DIR) \
		--platform manylinux_2_28_x86_64 \
		--platform manylinux_2_17_x86_64 \
		--python-version 3.12 \
		--implementation cp \
		--only-binary=:all: \
		--upgrade
