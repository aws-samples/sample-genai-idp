# IDP Accelerator SDLC Cloudformation
* This directory contains Cloudformation scripts useful to deploy SDLC infrastructure used during SDLC development.

# Prerequisites
* A Unix like operating system (Linux/Mac/WSL/Xenix/SunOS)

## Installation
* Install the `s3-Sourcecode.yml` cloudformation template.
* Install the `credential-vendor.yml` cloudformation template.
    * Enter the gitlab group name (e.g. `genaiic-reusable-assets/engagement-artifacts`)
    * Enter the gitlap project name (e.g. `genaiic-idp-accelerator`)
    * Enter the bucket name created in the last step (e.g. `idp-sdlc-source-code-YOUR_AWS_ACCOUNT-YOUR_REGION`)
* Customize `scripts/sdlc/idp-cli/Makefile` with your values.
* From the root of the repository run `make put -C ./scripts/sdlc/idp-cli`
    * This will ensure that an archive is there to install, when 
* Optional: Install the `sdlc-iam-role.yml` for least privilege sdlc operation (coming soon!)
* Install the `codepipeline-s3.yml` cloudformation template.
    * Optional: add the iam role created in the last step (e.g. `arn:aws:iam::YOUR_AWS_ACCOUNT:role/idp-sdlc-role`)
    * Be sure to replace the `idp-sdlc-source-code-YOUR_AWS_ACCOUNT-YOUR_REGION` with the name of the sourcecode bucket you created.
