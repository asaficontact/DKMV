/**
 * A tiny markdown-ish renderer for GitHub issue bodies + comments (FR-03-1,
 * AC-7). Ported from `issue.jsx`'s `MD`/`Inline`: it supports `### ` headings,
 * ordered (`1. `) and unordered (`- `) lists, inline `` `code` ``, and `**bold**`.
 *
 * It is deliberately **not** a full markdown engine — it renders the subset the
 * issue-detail screen needs, and it renders all text as **plain React nodes**
 * (never `dangerouslySetInnerHTML`), so an untrusted issue body cannot inject
 * markup (the body is attacker-controllable — OWASP LLM01 surface). All color is
 * token-driven via the `markdown` class (INV-14, no hex here).
 */

/** Inline spans: `` `code` `` and `**bold**`; everything else is plain text. */
export function Inline({ text }: { text: string }) {
  // Split on the two inline tokens, keeping the delimiters (the capturing group).
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
          return (
            <code key={i} className="mono md-code">
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
          return (
            <strong key={i} className="md-strong">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

const ORDERED = /^\d+\.\s/;
const UNORDERED = /^-\s/;

/**
 * Block renderer: walks the body line-by-line, grouping consecutive list lines
 * into a single `<ol>`/`<ul>`, lifting `### ` to an `<h4>`, and rendering blank
 * lines as spacers and everything else as a paragraph (with inline formatting).
 */
export default function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("### ")) {
      out.push(
        <h4 key={i} className="md-h">
          {line.slice(4)}
        </h4>,
      );
      i++;
      continue;
    }
    if (ORDERED.test(line)) {
      const items: string[] = [];
      while (i < lines.length && ORDERED.test(lines[i])) {
        items.push(lines[i].replace(ORDERED, ""));
        i++;
      }
      out.push(
        <ol key={`ol-${i}`} className="md-list">
          {items.map((t, j) => (
            <li key={j}>
              <Inline text={t} />
            </li>
          ))}
        </ol>,
      );
      continue;
    }
    if (UNORDERED.test(line)) {
      const items: string[] = [];
      while (i < lines.length && UNORDERED.test(lines[i])) {
        items.push(lines[i].slice(2));
        i++;
      }
      out.push(
        <ul key={`ul-${i}`} className="md-list">
          {items.map((t, j) => (
            <li key={j}>
              <Inline text={t} />
            </li>
          ))}
        </ul>,
      );
      continue;
    }
    if (line.trim() === "") {
      out.push(<div key={i} className="md-gap" />);
      i++;
      continue;
    }
    out.push(
      <p key={i} className="md-p">
        <Inline text={line} />
      </p>,
    );
    i++;
  }
  return <div className="markdown">{out}</div>;
}
