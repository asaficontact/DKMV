/**
 * YamlView tests (AC-7 / §5.8 FR-07-1v, ADR-P010).
 *
 * The "compiles to YAML" view is **read-only** (no editable input, no save
 * control) and renders the **verbatim** authoring-deferred note
 * "Workflow authoring coming in v1.1 — edit the YAML directly for now".
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import YamlView, { AUTHORING_DEFERRED_NOTE } from "./YamlView";

const COMPONENT_YAML = { filename: "component.yaml", content: "name: qa\nmax_budget_usd: 2.00\n" };
const TASK_YAML = [{ filename: "01-evaluate.yaml", content: "name: Evaluate\nprompt: assess\n" }];

describe("YamlView (AC-7)", () => {
  it("renders the verbatim authoring-deferred note", () => {
    render(<YamlView componentYaml={COMPONENT_YAML} taskYaml={TASK_YAML} />);
    expect(
      screen.getByText("Workflow authoring coming in v1.1 — edit the YAML directly for now"),
    ).toBeInTheDocument();
    // The exported constant is the exact string (guards against drift).
    expect(AUTHORING_DEFERRED_NOTE).toBe(
      "Workflow authoring coming in v1.1 — edit the YAML directly for now",
    );
  });

  it("renders the component + task YAML text", () => {
    render(<YamlView componentYaml={COMPONENT_YAML} taskYaml={TASK_YAML} />);
    expect(screen.getByText("component.yaml")).toBeInTheDocument();
    expect(screen.getByText("01-evaluate.yaml")).toBeInTheDocument();
    expect(screen.getByText(/max_budget_usd: 2.00/)).toBeInTheDocument();
    expect(screen.getByText(/name: Evaluate/)).toBeInTheDocument();
  });

  it("is read-only: no editable input and no save control", () => {
    const { container } = render(<YamlView componentYaml={COMPONENT_YAML} taskYaml={TASK_YAML} />);
    // No <textarea>, no <input>, nothing contentEditable.
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector('[contenteditable="true"]')).toBeNull();
    // No save / submit button.
    expect(screen.queryByRole("button", { name: /save|create|new workflow/i })).toBeNull();
    // A read-only badge surfaces the state.
    expect(screen.getByText("read-only")).toBeInTheDocument();
  });

  it("renders an empty note when there is no YAML on disk", () => {
    render(<YamlView componentYaml={null} taskYaml={[]} />);
    expect(screen.getByText(/No YAML on disk/)).toBeInTheDocument();
  });
});
