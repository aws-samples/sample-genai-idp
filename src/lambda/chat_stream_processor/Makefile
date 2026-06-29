# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Custom SAM build (Metadata.BuildMethod: makefile). Copies this package's
# sources, vendors the two chat processor modules (single source of truth — no
# duplicated logic in the repo), and installs Python dependencies into the SAM
# artifacts dir. idp_common itself comes from the attached Lambda layers, so we
# only install the thin web stack (fastapi/uvicorn) here.

build-ChatStreamProcessorFunction:
	mkdir -p $(ARTIFACTS_DIR)
	cp $(CURDIR)/app.py $(ARTIFACTS_DIR)/
	cp $(CURDIR)/sse.py $(ARTIFACTS_DIR)/
	cp $(CURDIR)/run.sh $(ARTIFACTS_DIR)/
	chmod +x $(ARTIFACTS_DIR)/run.sh
	# Vendor the processor sources under their importable module names.
	cp $(CURDIR)/../chat_with_document_processor/index.py $(ARTIFACTS_DIR)/chat_with_document_processor.py
	cp $(CURDIR)/../agent_chat_processor/index.py $(ARTIFACTS_DIR)/agent_chat_processor.py
	python -m pip install -r $(CURDIR)/requirements.txt -t $(ARTIFACTS_DIR)
