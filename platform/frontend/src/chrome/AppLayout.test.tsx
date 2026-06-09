/**
 * AppLayout chrome wrapper test. Asserts the extracted shell renders the Sidebar
 * (project switcher), the TopBar (title), and the screen's children — the
 * structural seam Board / IssueDetail / LiveRun all now share.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AppLayout from "./AppLayout";

describe("AppLayout", () => {
  it("renders the sidebar, the top-bar title, and the children", () => {
    render(
      <MemoryRouter>
        <AppLayout repoSlug="asaficontact/DKMV" title="asaficontact/DKMV · Run">
          <div data-testid="screen-body">hello</div>
        </AppLayout>
      </MemoryRouter>,
    );
    // The top-bar breadcrumb carries the title.
    expect(screen.getByText("asaficontact/DKMV · Run")).toBeInTheDocument();
    // The sidebar project switcher shows the repo name.
    expect(screen.getByText("DKMV")).toBeInTheDocument();
    // The children render inside the main column.
    expect(screen.getByTestId("screen-body")).toBeInTheDocument();
  });
});
