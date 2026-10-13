/**
 * Resolves the display title for a project, ensuring legacy/raw composer prefixes
 * such as "Idea: Project Name: ..." cleanly resolve to the actual saved project title.
 */
export function getDisplayProjectTitle(project?: { title?: string | null; description?: string | null } | null): string {
  if (!project || !project.title) return 'Untitled Project';
  const title = project.title.trim();

  // If title was prefixed with "Idea: Project Name:" or "Idea: Title:"
  const prefixMatch = title.match(/^Idea:\s*(?:Project\s*Name|Project\s*Title|Title)\s*:\s*(.+)$/i);
  if (prefixMatch && prefixMatch[1]?.trim()) {
    // If description has the full name, prefer it to recover any substring truncation
    if (project.description) {
      const descMatch = project.description.match(/^\s*(?:Project\s*Name|Project\s*Title|Title)\s*:\s*([^\r\n]+)/im);
      if (descMatch && descMatch[1]?.trim()) {
        return descMatch[1].trim();
      }
    }
    return prefixMatch[1].replace(/\.\.\.$/, '').trim();
  }

  return title;
}
