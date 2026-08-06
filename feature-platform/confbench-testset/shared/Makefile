# SAM `BuildMethod: makefile` target for the shared layer.
#
# Why a makefile instead of `BuildMethod: python3.12`: that build method runs
# PythonPipBuilder, which installs a requirements.txt and does NOT copy
# hand-authored source — variants.py would be dropped from the layer. And with
# no BuildMethod at all, SAM leaves ContentUri as a relative path pointing
# outside .aws-sam/build, which breaks `sam package`.
#
# ARTIFACTS_DIR is supplied by SAM. Lambda puts a layer's `python/` directory on
# sys.path, so the module must land at $(ARTIFACTS_DIR)/python/variants.py.
build-SharedLayer:
	mkdir -p "$(ARTIFACTS_DIR)/python"
	cp python/variants.py "$(ARTIFACTS_DIR)/python/variants.py"
