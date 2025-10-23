IDP_ACCOUNT_ID?=020432867916
AWS_REGION?=us-east-1
IDP_ADMIN_EMAIL?=strahanr@amazon.com
IDP_CWD?=../../../
DEBUG?=True

INSTALL_BUCKET?=none
SDLC_SOURCE_CODE_BUCKET?=idp-sdlc-sourcecode-$(IDP_ACCOUNT_ID)-$(AWS_REGION)
IDP_CFN_PREFIX?=idp-dev
IDP_STACK_NAME?=$(IDP_CFN_PREFIX)
IDP_PIPELINE_NAME?=idp-sdlc-deploy-pipeline

test:
	poetry run pytest -s --log-cli-level=DEBUG

cfn-prefix:
	@ echo "idp-$(shell date +%y%m%d-%H%M-%S)"

install:
	poetry run idpcli install \
	--account-id=$(IDP_ACCOUNT_ID) \
	--cfn-prefix=$(IDP_CFN_PREFIX) \
	--cwd=$(IDP_CWD) \
	--admin-email=$(IDP_ADMIN_EMAIL) \
	--debug

uninstall:
	export S3UTIL_ALLOW_BUCKET_DESTRUCT=true && \
	poetry run idpcli uninstall \
	--stack-name=$(IDP_STACK_NAME) \
	--account-id=$(IDP_ACCOUNT_ID) \
	--cfn-prefix=$(IDP_CFN_PREFIX)
	# Clean up CloudWatch Logs resource policy after uninstall
	cd $(IDP_CWD) && python3 scripts/cleanup-logs.py || echo "Log cleanup failed but continuing" \

smoketest:
	poetry run idpcli smoketest \
	--stack-name=$(IDP_STACK_NAME)

wait:
	$(eval VERSION_ID := $(shell cat $(IDP_CWD)/.upload_version_id 2>/dev/null || echo ""))
	@if [ -z "$(VERSION_ID)" ]; then echo "Error: No version ID found"; exit 1; fi
	$(eval EXECUTION_ID := $(shell poetry run python -c "from idp_cli.util.codepipeline_util import CodePipelineUtil; print(CodePipelineUtil.get_execution_id_by_version('$(IDP_PIPELINE_NAME)', '$(VERSION_ID)'))" || echo "FAILED"))
	@if [ "$(EXECUTION_ID)" = "FAILED" ]; then echo "Error: Failed to find pipeline execution for version $(VERSION_ID)"; exit 1; fi
	poetry run idpcli monitor-pipeline \
	--pipeline-name=$(IDP_PIPELINE_NAME) \
	--execution-id=$(EXECUTION_ID) \
	--initial-wait=0 \
	--max-wait=120

put: zip
	$(eval VERSION_ID := $(shell cd $(IDP_CWD) && aws s3api put-object --bucket $(SDLC_SOURCE_CODE_BUCKET) --key deploy/code.zip --body ./dist/code.zip --query 'VersionId' --output text))
	@echo "Uploaded with version ID: $(VERSION_ID)"
	@echo "$(VERSION_ID)" > $(IDP_CWD)/.upload_version_id

zip:
	cd $(IDP_CWD) && \
	mkdir -p ./dist && \
	rm -f ./dist/code.zip && \
	zip -r ./dist/code.zip ./ \
		-x "*.git/*" \
		-x "*.git/**" \
		-x "*__pycache__/*" \
		-x ".gitlab-ci.yml" \
		-x "*.delete/*" \
		-x "*.sav/*" \
		-x "*.venv/*" \
		-x "*.vscode/*" \
		-x "*cdk.out/*" \
		-x "*dist/*" \
		-x "*.DS_Store" \
		-x "*.pyc" \
		-x "*.pyo" \
		-x "*.pyd" \
		-x "*.so" \
		-x "**/.env" \
		-x "*.docker/*" \
		-x "*.aws-sam/*"
