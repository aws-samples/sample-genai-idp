# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from idp_common.utils.s3util import S3Util


@dataclass
class BdaInvocation:
    """An object to ease consumption of DBA results from S3"""

    bucket_name: Optional[str] = field(default=None)
    job_id: Optional[str] = field(default=None)
    custom_output_segments: Optional[List[Dict[str, Any]]] = field(default=None)
    job_metadata: Optional[Dict[str, Any]] = field(default=None)

    @staticmethod
    def from_s3(s3_url: str) -> "BdaInvocation":
        """
        Create and populate a BdaInvocation object with data from S3 based on job_id.

        Args:
            job_id (str): The BDA job ID
            bucket_name (str): The S3 bucket name where job data is stored

        Returns:
            BdaInvocation: A populated BdaInvocation object
        """
        # Construct the path to the job metadata file
        # job_metadata_key = f"output-docs/{job_id}/job_metadata.json"
        bucket_name, job_metadata_key = S3Util.s3_url_to_bucket_key(s3_url=s3_url)

        # Get the job metadata from S3
        job_metadata = S3Util.get_dict(bucket_name, job_metadata_key)

        # Create and return a new BdaInvocation object
        return BdaInvocation(
            bucket_name=bucket_name,
            job_id=job_metadata["job_id"],
            job_metadata=job_metadata,
        )

    def get_custom_output(
        self, asset_id: int = 0, segment_index: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieve the custom output from the BDA job.

        Args:
            asset_id (int): The asset ID in the output_metadata array (default: 0)
            segment_index (int): The segment index in the segment_metadata array (default: 0)

        Returns:
            dict: The custom output data from the BDA job

        Raises:
            ValueError: If job_metadata is not populated or no custom output is found
        """
        if not self.job_metadata:
            raise ValueError("Job metadata not populated. Use from_s3() first.")

        try:
            # Extract the output metadata for the specified asset
            output_metadata_list = self.job_metadata.get("output_metadata", [])
            if not output_metadata_list or asset_id >= len(output_metadata_list):
                raise ValueError(f"No output metadata found for asset ID {asset_id}")

            output_metadata = output_metadata_list[asset_id]

            # Get the segment metadata for the specified segment index
            segment_metadata_list = output_metadata.get("segment_metadata", [])
            if not segment_metadata_list or segment_index >= len(segment_metadata_list):
                raise ValueError(
                    f"No segment metadata found for segment index {segment_index}"
                )

            segment_metadata = segment_metadata_list[segment_index]

            # Get the custom output path
            custom_output_path = segment_metadata.get("custom_output_path")
            if not custom_output_path:
                raise ValueError(
                    f"No custom output path found for asset ID {asset_id}, segment index {segment_index}"
                )

            # Parse the S3 URI to get bucket and key
            if custom_output_path.startswith("s3://"):
                bucket, key = S3Util.s3_url_to_bucket_key(s3_url=custom_output_path)

                # Get the custom output from S3
                custom_output = S3Util.get_dict(bucket, key)

                # Store the result in the custom_output_segments if it's None
                if self.custom_output_segments is None:
                    self.custom_output_segments = []

                # Ensure the list is long enough
                while len(self.custom_output_segments) <= asset_id:
                    self.custom_output_segments.append({})

                # Store the custom output
                self.custom_output_segments[asset_id] = custom_output

                return custom_output
            else:
                raise ValueError(f"Invalid S3 URI format: {custom_output_path}")

        except Exception as e:
            raise ValueError(f"Error retrieving custom output: {str(e)}")
