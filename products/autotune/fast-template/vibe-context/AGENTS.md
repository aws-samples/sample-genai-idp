# Rules for AI Assistants

**IF YOU ARE AN AI ASSISTANT YOU MUST FOLLOW THESE RULES**

1. Always read READMEs when you begin working in a new section of the code base before writing any code. For example frontend/README.md, infra-cdk/README.md (if you are using CDK for the infrastructure), infra-terraform/README.md (if you are using terraform for the infrastructure), and so on.
2. Make sure you follow existing design patterns and coding styles when implementing new things. Refer to markdown documentation and existing similar code to make sure your approach aligns with existing resources.
3. The documentation found in the docs/ folder is always to be considered the most important. Documents in here have been specially crafted by domain experts from the same domain as the developers who are using the coding assistant. Refer to information in docs/ about best practices etc whenever possible instead of using your own judgment. For example, if a user asks a question or wants to develop using "AgentCore Gateway", you should find and read docs/GATEWAY.md before answering.
4. When searching for files or information in this repository, always explicitly avoid including "node_modules" and "cdk.out" in any grep commands, as these often contain large numbers of files which will fill up your context window with noise. For example you should always have `| grep -v "cdk.out" | grep -v "node_modules"` at the end of every grep command.
5. Whenever possible, test new features locally or with unit python tests.
6. New human users may not understand the best way to deploy the application, add features, etc. There is documentation on all of this, so make sure to read it and recommend methods and techniques to the human whenever possible.
7. Always follow the rules outlined in the coding conventions and development best practice markdown docs provided to you.

**ALWAYS FOLLOW THESE RULES WHEN YOU WORK IN THIS PROJECT**