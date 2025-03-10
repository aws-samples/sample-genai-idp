# Copyright © Amazon.com and Affiliates: 
# This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties. 
# The libraries used in this developed content are subject to their respective license disclosures. 
# Please see the license and SBOM artifact files included in this repository for specific license references.

import os
import pathlib
from typing import Optional 

class PathUtil():
    @staticmethod
    def root(path: Optional[str] = None):

        join_path = [pathlib.Path(__file__).parent.resolve(), ".."]

        if path:
            join_path.append(path)

        p = os.path.join(
            *join_path
        )
        return p
