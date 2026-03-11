import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import remarkGithubVideo from "./plugins/remark-github-video.mjs";

export default defineConfig({
  site: "https://aws-solutions-library-samples.github.io",
  base: "/accelerated-intelligent-document-processing-on-aws",
  markdown: {
    remarkPlugins: [remarkGithubVideo],
  },
  integrations: [
    starlight({
      title: "GenAI IDP",
      description:
        "GenAI Intelligent Document Processing — scalable, serverless AWS solution for automated document processing",
      logo: {
        dark: "./src/assets/logo-dark.svg",
        light: "./src/assets/logo-light.svg",
        replacesTitle: false,
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws",
        },
      ],
      customCss: ["./src/styles/custom.css"],
      sidebar: [
        {
          label: "Overview",
          items: [{ label: "Welcome", slug: "index" }],
        },
        {
          label: "Core",
          items: [
            { label: "Architecture", slug: "architecture" },
            { label: "Deployment", slug: "deployment" },
            { label: "Configuration", slug: "configuration" },
            {
              label: "Configuration Versions",
              slug: "configuration-versions",
            },
            {
              label: "Configuration Best Practices",
              slug: "idp-configuration-best-practices",
            },
            {
              label: "JSON Schema Migration",
              slug: "json-schema-migration",
            },
            { label: "Web UI", slug: "web-ui" },
            { label: "IDP CLI", slug: "idp-cli" },
            { label: "IDP SDK", slug: "idp-sdk" },
            { label: "Demo Videos", slug: "demo-videos" },
            { label: "Troubleshooting", slug: "troubleshooting" },
            { label: "Error Analyzer", slug: "error-analyzer" },
          ],
        },
        {
          label: "Processing Modes",
          items: [
            { label: "BDA Mode Reference", slug: "pattern-1" },
            { label: "Pipeline Mode Reference", slug: "pattern-2" },
            { label: "Discovery", slug: "discovery" },
          ],
        },
        {
          label: "Document Processing Features",
          items: [
            { label: "Classification", slug: "classification" },
            { label: "Extraction", slug: "extraction" },
            { label: "Assessment", slug: "assessment" },
            {
              label: "Assessment Bounding Boxes",
              slug: "assessment-bounding-boxes",
            },
            { label: "Few-Shot Examples", slug: "few-shot-examples" },
            { label: "Human-in-the-Loop Review", slug: "human-review" },
            { label: "Rule Validation", slug: "rule-validation" },
            { label: "Criteria Validation", slug: "criteria-validation" },
            {
              label: "OCR Image Sizing Guide",
              slug: "ocr-image-sizing-guide",
            },
            { label: "Languages", slug: "languages" },
          ],
        },
        {
          label: "Evaluation & Testing",
          items: [
            { label: "Evaluation Framework", slug: "evaluation" },
            {
              label: "Enhanced Reporting",
              slug: "evaluation-enhanced-reporting",
            },
            { label: "Test Studio", slug: "test-studio" },
          ],
        },
        {
          label: "AI Agents & Analytics",
          items: [
            { label: "Agent Analysis", slug: "agent-analysis" },
            { label: "Agent Companion Chat", slug: "agent-companion-chat" },
            { label: "Code Intelligence", slug: "code-intelligence" },
            { label: "Knowledge Base", slug: "knowledge-base" },
            { label: "Custom MCP Agent", slug: "custom-mcp-agent" },
            { label: "MCP Integration", slug: "mcp-integration" },
          ],
        },
        {
          label: "Integration & Extensions",
          items: [
            {
              label: "Post-Processing Lambda Hook",
              slug: "post-processing-lambda-hook",
            },
            {
              label: "Lambda Hook Inference",
              slug: "lambda-hook-inference",
            },
            { label: "Nova Fine-Tuning", slug: "nova-finetuning" },
            { label: "Service Tiers", slug: "service-tiers" },
          ],
        },
        {
          label: "Monitoring & Operations",
          items: [
            { label: "Monitoring", slug: "monitoring" },
            { label: "Reporting Database", slug: "reporting-database" },
            { label: "Capacity Planning", slug: "capacity-planning" },
            { label: "Cost Calculator", slug: "cost-calculator" },
          ],
        },
        {
          label: "Planning & Security",
          items: [
            {
              label: "Well-Architected Assessment",
              slug: "well-architected",
            },
            {
              label: "AWS Services & IAM Roles",
              slug: "aws-services-and-roles",
            },
            { label: "GovCloud Deployment", slug: "govcloud-deployment" },
            {
              label: "EU Region Model Support",
              slug: "eu-region-model-support",
            },
          ],
        },
        {
          label: "Development Setup",
          items: [
            { label: "Setup: Linux", slug: "setup-development-env-linux" },
            { label: "Setup: macOS", slug: "setup-development-env-macos" },
            { label: "Setup: WSL", slug: "setup-development-env-wsl" },
            {
              label: "Using Notebooks",
              slug: "using-notebooks-with-idp-common",
            },
          ],
        },
        {
          label: "Migration",
          items: [
            { label: "v0.4 → v0.5 Migration", slug: "migration-v04-to-v05" },
          ],
        },
      ],
    }),
  ],
  // Disable image optimization for content images (our docs reference ../images/ which are symlinked)
  image: {
    service: {
      entrypoint: "astro/assets/services/noop",
    },
  },
});
