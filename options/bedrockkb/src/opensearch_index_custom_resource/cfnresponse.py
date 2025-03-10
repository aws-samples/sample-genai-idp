# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import urllib3
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SUCCESS = "SUCCESS"
FAILED = "FAILED"

def send(event, context, responseStatus, responseData, physicalResourceId, reason):
    responseUrl = event['ResponseURL']

    logger.info('<<cfnresponse.send>>: responseURL = {}'.format(responseUrl))

    responseBody = {}
    responseBody['Status'] = responseStatus
    responseBody['Reason'] = ('Reason: ' + json_dump_format(reason) +
            '. See the details in CloudWatch Log Stream: ' + context.log_stream_name)
    responseBody['PhysicalResourceId'] = physicalResourceId or context.log_stream_name
    responseBody['StackId'] = event['StackId']
    responseBody['RequestId'] = event['RequestId']
    responseBody['LogicalResourceId'] = event['LogicalResourceId']
    responseBody['Data'] = responseData

    json_responseBody = json_dump_format(responseBody)

    logger.info('<<cfnresponse.send>>: response body = {}'.format(json.dumps(responseBody)))

    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }

    try:
        http = urllib3.PoolManager()
        response = http.request('PUT', responseUrl,
                                headers=headers, body=json_responseBody)
        logger.info('<<cfnresponse.send>>: status code = {}'.format(response.status))
        return json_responseBody
    except Exception as e:
        logger.info('<<cfnresponse.send>>: failed executing requests.put(..): ' + str(e))
        return {'exception': str(e)}


def json_dump_format(obj):
    return json.dumps(obj, indent=4, sort_keys=True, default=str)
