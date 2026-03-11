/**
 * Remark plugin that converts bare GitHub video URLs into <video> elements.
 *
 * GitHub's markdown renderer auto-embeds URLs like:
 *   https://github.com/user-attachments/assets/<id>
 * as inline video players. Standard markdown renderers (including Astro/Starlight)
 * just render them as plain text links.
 *
 * This plugin walks the markdown AST and replaces any paragraph that contains
 * only a single bare GitHub video URL with an HTML <video> element.
 */
import { visit } from "unist-util-visit";

const GITHUB_VIDEO_RE =
  /^https:\/\/github\.com\/user-attachments\/assets\/[\w-]+$/;

export default function remarkGithubVideo() {
  return (tree) => {
    visit(tree, "paragraph", (node, index, parent) => {
      // Match paragraphs that contain exactly one child
      if (node.children.length !== 1) return;

      const child = node.children[0];

      // Check for both text nodes (raw URL) and link nodes (autolinked URL)
      let url = null;
      if (child.type === "text" && GITHUB_VIDEO_RE.test(child.value.trim())) {
        url = child.value.trim();
      } else if (
        child.type === "link" &&
        GITHUB_VIDEO_RE.test(child.url) &&
        child.children.length === 1 &&
        child.children[0].type === "text"
      ) {
        url = child.url;
      }

      if (!url) return;

      // Replace the paragraph with an HTML video element
      parent.children[index] = {
        type: "html",
        value: `<video controls playsinline width="100%" style="max-width:100%; border-radius:8px; border:1px solid var(--sl-color-gray-4, #ddd);">
  <source src="${url}" type="video/mp4" />
  <a href="${url}">Watch video</a>
</video>`,
      };
    });
  };
}
