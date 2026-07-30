build-FinetuningProcessDocumentFunction:
	mkdir -p $(ARTIFACTS_DIR)
	cp $(CURDIR)/*.py $(ARTIFACTS_DIR)/
	python -m pip install -r $(CURDIR)/requirements.txt -t $(ARTIFACTS_DIR) \
		--platform manylinux_2_28_x86_64 \
		--platform manylinux_2_17_x86_64 \
		--python-version 3.12 \
		--implementation cp \
		--only-binary=:all: \
		--upgrade
