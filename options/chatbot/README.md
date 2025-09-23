# Embeddable Chatbot for Amazon Bedrock Knowledge Base

This guide provides all the necessary steps to deploy and integrate a secure, embeddable chat widget into your web application. The widget uses Amazon Lex V2 and a secure API Gateway backend to connect to your **existing** Amazon Bedrock Knowledge Base.

## Architecture Overview

The solution consists of three main parts:

1.  **AWS Backend (CloudFormation)**: The provided `template.yaml` deploys an AWS Lambda, an Amazon API Gateway, and an Amazon Lex V2 bot. This creates a secure API endpoint that connects to your Bedrock Knowledge Base.
2.  **Secure Authentication**: Access to the API is secured using a JSON Web Token (JWT). Your application's backend server will generate this token to authorize the frontend widget to communicate with the chatbot API.
3.  **Frontend Widget**: The chat interface is powered by the open-source [AWS Lex Web UI](https://github.com/aws-samples/aws-lex-web-ui), which is embedded into your website.

![Architecture Diagram](https://user-images.githubusercontent.com/12977329/222872332-9c16969b-92aa-450c-9120-2e0de795e691.png)

---

## 1. Deployment Steps

### Prerequisites

*   An AWS Account with permissions to create the resources in the template.
*   The **AWS CLI** installed and configured.
*   The **ID of your existing Amazon Bedrock Knowledge Base**.
*   **Node.js** and **npm** installed on your backend server to generate the JWT.

### Deploying the CloudFormation Stack

1.  **Choose a Strong JWT Secret**: Create a secure, random string that is at least 32 characters long. You can use a password generator for this. This secret will be used to sign and verify authentication tokens.

2.  **Deploy via AWS CLI**: Open your terminal and run the following command. Replace the placeholder values with your own.

    ```bash
    aws cloudformation deploy \
      --template-file template.yaml \
      --stack-name bedrock-chat-widget \
      --parameter-overrides \
        BedrockKnowledgeBaseId="YOUR_KB_ID_HERE" \
        JwtSecret="YOUR_STRONG_JWT_SECRET_HERE" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
      --region us-east-1 # Or your preferred AWS region
    ```

3.  **Get API Endpoint from Outputs**: Once the deployment is complete, go to the AWS CloudFormation console, select your stack (`bedrock-chat-widget`), and navigate to the **Outputs** tab. Copy the value for `ChatEndpointURL`. You will need this for the frontend integration.

---

## 2. Backend Integration: JWT Generation (Crucial Security Step)

To prevent unauthorized use of your chatbot API, the chat widget must be initialized with a short-lived JSON Web Token (JWT). Your application's backend server is responsible for generating this token.

Here is a sample implementation in **Node.js**.

1.  **Install the library**:
    ```bash
    npm install jsonwebtoken
    ```

2.  **Create a token generation function**: Add this code to your backend, for example, in an API route that is called by your frontend when the page loads.

    ```javascript
    // Example: /pages/api/generate-token.js
    const jwt = require('jsonwebtoken');

    // IMPORTANT: Use the SAME secret you provided during CloudFormation deployment.
    // Best practice is to store this in an environment variable (e.g., process.env.JWT_SECRET).
    const JWT_SECRET = "YOUR_STRONG_JWT_SECRET_HERE";

    /**
     * Generates a short-lived JWT for the chat widget.
     * @param {string} userId - A unique identifier for the user.
     * @returns {string} The generated JWT.
     */
    function generateChatToken(userId) {
      const payload = {
        // 'sub' (subject) is a standard JWT claim for the user ID.
        // You can add other relevant, non-sensitive data here.
        sub: userId,
      };

      const options = {
        // The token will expire in 15 minutes. The widget should request a
        // new token if the session lasts longer.
        expiresIn: '15m',
      };

      const token = jwt.sign(payload, JWT_SECRET, options);
      return token;
    }

    // --- Example Usage ---
    // In your authenticated API route, generate a token for the logged-in user.
    const user = { id: 'user-12345' }; // Get the user from your session
    const chatToken = generateChatToken(user.id);

    // Send the token to the frontend
    // res.status(200).json({ token: chatToken });
    console.log('Generated Token:', chatToken);
    ```

---

## 3. Frontend Embedding

Embed the official `aws-lex-web-ui` component into your website's HTML. The following snippet includes the necessary configuration to connect to your new API Gateway endpoint and send the JWT for authentication.

1.  **Fetch the Token**: Your frontend code should first make a request to your backend to get the `chatToken` generated in the previous step.

2.  **Add the HTML Snippet**: Place this code in your HTML file where you want the chat widget to appear.

    ```html
    <!DOCTYPE html>
    <html>
    <head>
      <title>My Application</title>
      <!-- The loader script for the AWS Lex Web UI -->
      <script src="https://assets.amazonaws.com/connect-assets/lex-web-ui-loader.min.js"></script>
    </head>
    <body>
      <h1>Welcome to my website</h1>
      <p>Ask a question in the chat widget!</p>

      <script>
        // This function runs once the loader script is ready.
        function onLexWebUiReady() {
          // STEP 1: Fetch the JWT from your backend.
          // This is an example using fetch. Replace with your actual API endpoint.
          fetch('/api/generate-token') // Assumes you created this backend route
            .then(response => response.json())
            .then(data => {
              const jwtToken = data.token;

              // Configuration for the Lex Web UI
              const config = {
                ui: {
                  // The title of the chat window
                  toolbarTitle: 'Company Support',
                  // You can disable the initial welcome message from the UI
                  // since our bot has its own greetings.
                  shouldShowIntroMessage: false,
                },
                aws: {
                  // The API Gateway endpoint for your chatbot
                  apiGateway: {
                    invokeUrl: 'YOUR_CHAT_ENDPOINT_URL_HERE', // <-- PASTE THE URL FROM CLOUDFORMATION OUTPUTS
                    // IMPORTANT: This passes the JWT to the API Gateway Authorizer
                    customHeaders: {
                      Authorization: 'Bearer ' + jwtToken,
                    }
                  }
                }
              };

              // Instantiate the chat widget with the configuration
              window.LexWebUi.newChat(config);
            })
            .catch(console.error);
        }

        // Add the function as an event listener
        document.addEventListener('lexWebUiReady', onLexWebUiReady, false);
      </script>
    </body>
    </html>
    ```

3.  **Final Configuration**:
    *   Replace `YOUR_CHAT_ENDPOINT_URL_HERE` with the `ChatEndpointURL` value from your CloudFormation stack's outputs.
    *   Ensure the `fetch` URL (`/api/generate-token`) matches the actual API endpoint you created on your backend for generating JWTs.

You have now successfully deployed and integrated a secure, AI-powered chatbot into your website!
