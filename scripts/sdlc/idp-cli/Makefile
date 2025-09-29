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
	--cfn-prefix=$(IDP_CFN_PREFIX) \

smoketest:
	poetry run idpcli smoketest \
	--stack-name=$(IDP_STACK_NAME)

wait:
	poetry run idpcli monitor-pipeline \
	--pipeline-name=$(IDP_PIPELINE_NAME) \
	--initial-wait=180 \
	--max-wait=60

put: zip
	cd $(IDP_CWD) && \
	aws s3 cp ./dist/code.zip s3://$(SDLC_SOURCE_CODE_BUCKET)/deploy/code.zip --force

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
