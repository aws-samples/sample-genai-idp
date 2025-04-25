# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""CodeBuild Starter Lambda Function"""
import logging
from os import getenv

import boto3
from botocore.config import Config as BotoCoreConfig
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
    CLIENT = boto3.client("codebuild", config=CLIENT_CONFIG)
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
            response = CLIENT.start_build(projectName=project_name)
            build_id = response["build"]["id"]
            HELPER.Data["build_id"] = build_id
        except Exception as exception:  # pylint: disable=broad-except
            LOGGER.error("failed to start build - exception: %s", exception)
            raise

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
            response = CLIENT.batch_get_builds(ids=[build_id])
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

    raise RuntimeError(f"Invalid resource type: {resource_type}")


@HELPER.delete
def delete_no_op(event, _):
    """Delete Resource"""
    LOGGER.info("delete event ignored: %s", event)


def handler(event, context):
    """Lambda Handler"""
    HELPER(event, context)
