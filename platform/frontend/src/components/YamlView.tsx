/**
 * Read-only "compiles to YAML" peek (Screen F's YAML view — F12 / §5.8 FR-07-1v,
 * ADR-P010). Renders the selected component's `component.yaml` + each task
 * `*.yaml` text **read-only**: monospace `<pre>` blocks, **no editable input, no
 * save control, no "new workflow" CTA**. Authoring is deferred to v1.1.
 *
 * The **verbatim** authoring-deferred note —
 * "Workflow authoring coming in v1.1 — edit the YAML directly for now" — renders
 * as warm, plain microcopy (P4), not error/blocker styling (AC-7; the §9 grep
 * matches this exact string).
 *
 * **INV-14.** No hex — color is token-driven; the note is a calm info line, the
 * code is the mono token style. The YAML is presentational text only (it is
 * never parsed/edited here).
 */
import type { WorkflowYaml } from "../api/workflows";
import { SparkleIcon } from "./icons";

/** The exact authoring-deferred note (AC-7 — the §9 grep matches this string). */
export const AUTHORING_DEFERRED_NOTE =
  "Workflow authoring coming in v1.1 — edit the YAML directly for now";

export interface YamlViewProps {
  /** The component manifest text (`component.yaml`/`.yml`), or null when absent. */
  componentYaml: WorkflowYaml | null;
  /** The task `*.yaml` documents, in on-disk task order. */
  taskYaml: WorkflowYaml[];
}

/** Render one read-only YAML document (filename header + monospace `<pre>`). */
function YamlDoc({ doc }: { doc: WorkflowYaml }) {
  return (
    <figure className="yaml-doc">
      <figcaption className="cap mono yaml-doc-name">{doc.filename}</figcaption>
      {/* Read-only: a <pre> text block — no <textarea>, no contentEditable. */}
      <pre className="yaml-code mono" tabIndex={0}>
        {doc.content}
      </pre>
    </figure>
  );
}

/**
 * Render the read-only YAML peek: the authoring-deferred note, the
 * `component.yaml`, then the task documents. No editor / save / new-workflow CTA.
 */
export default function YamlView({ componentYaml, taskYaml }: YamlViewProps) {
  const empty = componentYaml == null && taskYaml.length === 0;
  return (
    <section className="yaml-view" aria-label="Compiles to YAML (read-only)">
      <div className="yaml-view-head">
        <h3 className="yaml-view-title cap">Compiles to YAML</h3>
        <span className="badge badge-soft yaml-readonly-badge">read-only</span>
      </div>

      <p className="yaml-authoring-note">
        <SparkleIcon size={13} />
        {AUTHORING_DEFERRED_NOTE}
      </p>

      {empty ? (
        <p className="cap yaml-empty">No YAML on disk for this component.</p>
      ) : (
        <div className="yaml-docs">
          {componentYaml && <YamlDoc doc={componentYaml} />}
          {taskYaml.map((doc) => (
            <YamlDoc key={doc.filename} doc={doc} />
          ))}
        </div>
      )}
    </section>
  );
}
