# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""CodeBuild starter and ECR cleanup Lambda function used by Pattern 2 deployments."""
import logging
from os import getenv
import json
from typing import List

import boto3
from botocore.config import Config as BotoCoreConfig
from botocore.exceptions import ClientError
from crhelper import CfnResource


LOGGER = logging.getLogger(__name__)
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")
HELPER = CfnResource(
    json_logging=True,
    log_level=LOG_LEVEL,
)

# global init code goes here so that it can pass failure in case
# of an exception
try:
    # boto3 client
    CLIENT_CONFIG = BotoCoreConfig(
        retries={"mode": "adaptive", "max_attempts": 5},
    )
    CODEBUILD_CLIENT = boto3.client("codebuild", config=CLIENT_CONFIG)
    ECR_CLIENT = boto3.client("ecr", config=CLIENT_CONFIG)
except Exception as init_exception:  # pylint: disable=broad-except
    HELPER.init_failure(init_exception)


@HELPER.create
@HELPER.update
def create_or_update(event, _):
    """Create or Update Resource"""
    resource_type = event["ResourceType"]
    resource_properties = event["ResourceProperties"]

    if resource_type == "Custom::CodeBuildRun":
        try:
            project_name = resource_properties["BuildProjectName"]
            response = CODEBUILD_CLIENT.start_build(projectName=project_name)
            build_id = response["build"]["id"]
            HELPER.Data["build_id"] = build_id
        except Exception as exception:  # pylint: disable=broad-except
            LOGGER.error("failed to start build - exception: %s", exception)
            raise

        return

    if resource_type == "Custom::ECRRepositoryCleanup":
        repository_name = resource_properties["RepositoryName"]
        LOGGER.info("registered ECR cleanup resource for repository %s", repository_name)
        HELPER.Data["repository_name"] = repository_name
        return

    raise ValueError(f"invalid resource type: {resource_type}")


@HELPER.poll_create
@HELPER.poll_update
def poll_create_or_update(event, _):
    """Create or Update Poller"""
    resource_type = event["ResourceType"]
    helper_data = event["CrHelperData"]

    if resource_type == "Custom::CodeBuildRun":
        try:
            build_id = helper_data["build_id"]
            response = CODEBUILD_CLIENT.batch_get_builds(ids=[build_id])
            LOGGER.info(response)

            builds = response["builds"]
            if not builds:
                raise RuntimeError("could not find build")

            build = builds[0]
            build_status = build["buildStatus"]
            LOGGER.info("build status: [%s]", build_status)

            if build_status == "SUCCEEDED":
                LOGGER.info("returning True")
                return True

            if build_status == "IN_PROGRESS":
                LOGGER.info("returning None")
                return None

            raise RuntimeError(f"build did not complete - status: [{build_status}]")

        except Exception as exception:  # pylint: disable=broad-except
            LOGGER.error("build poller - exception: %s", exception)
            raise

    if resource_type == "Custom::ECRRepositoryCleanup":
        LOGGER.info("ECR cleanup resource create/update completed")
        return True

    raise RuntimeError(f"Invalid resource type: {resource_type}")


@HELPER.delete
def delete_resource(event, _):
    """Delete Resource"""
    resource_type = event["ResourceType"]

    if resource_type == "Custom::CodeBuildRun":
        LOGGER.info("delete event ignored for CodeBuild custom resource: %s", event)
        return

    if resource_type == "Custom::ECRRepositoryCleanup":
        repository_name = event["ResourceProperties"]["RepositoryName"]
        LOGGER.info("starting cleanup for repository %s", repository_name)
        try:
            _delete_all_ecr_images(repository_name)
        except ClientError as error:
            if error.response["Error"]["Code"] == "RepositoryNotFoundException":
                LOGGER.info("repository %s already deleted", repository_name)
                return
            LOGGER.error(
                "failed to purge repository %s - error: %s",
                repository_name,
                error,
            )
            raise
        except Exception as unknown_exception:  # pylint: disable=broad-except
            LOGGER.error(
                "unexpected error while cleaning repository %s - error: %s",
                repository_name,
                unknown_exception,
            )
            raise

        LOGGER.info("cleanup for repository %s completed", repository_name)
        return

    LOGGER.warning("received delete for unsupported resource type: %s", resource_type)


def _delete_all_ecr_images(repository_name: str) -> None:
    """Delete every image (tagged and untagged) from the ECR repository."""
    paginator = ECR_CLIENT.get_paginator("list_images")
    images_to_delete: List[dict] = []

    for page in paginator.paginate(repositoryName=repository_name):
        image_ids = page.get("imageIds", [])
        if not image_ids:
            continue
        images_to_delete.extend(image_ids)
        LOGGER.debug(
            "queued %s images for deletion from repository %s",
            len(image_ids),
            repository_name,
        )

    if not images_to_delete:
        LOGGER.info("no images found in repository %s", repository_name)
        return

    for chunk_start in range(0, len(images_to_delete), 100):
        chunk = images_to_delete[chunk_start : chunk_start + 100]
        LOGGER.debug(
            "deleting %s images from repository %s",
            len(chunk),
            repository_name,
        )
        ECR_CLIENT.batch_delete_image(repositoryName=repository_name, imageIds=chunk)


def handler(event, context):
    """Lambda Handler"""
    LOGGER.info("Received event: %s", json.dumps(event))
    HELPER(event, context)
