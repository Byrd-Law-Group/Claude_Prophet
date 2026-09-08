// Minimal, dependency-free inline Markdown for short author-written notes.
// Supports **bold** and [text](href) only. Escapes HTML first so the output
// is safe even though this content comes from our own Markdown frontmatter.
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export function marked(input: string): string {
  let out = escapeHtml(input);
  // Links: [label](href)
  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, label, href) => `<a href="${href}">${label}</a>`
  );
  // Bold: **text**
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  return out;
}
