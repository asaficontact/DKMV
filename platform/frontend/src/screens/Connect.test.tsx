/**
 * Connect flow render tests (AC-10, AC-11, AC-12 / FR-01).
 *
 * Covers: the disconnected hero lists the four PAT permissions + the verbatim
 * reassurance copy; connecting stores the PAT and advances to the picker; the
 * picker renders `GET /repos`, the "What we'll do" confirm rows and the
 * preflight box; "Open project" triggers `POST /projects/{repo}/sync` and
 * `onDone`. The api/connect module is mocked so no real network is touched.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreflightReport, Repo } from "../api/connect";

const mocks = vi.hoisted(() => ({
  connectGitHub: vi.fn(),
  listRepos: vi.fn(),
  getPreflight: vi.fn(),
  syncProject: vi.fn(),
}));

vi.mock("../api/connect", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/connect")>();
  return { ...actual, ...mocks };
});

import Connect from "./Connect";

const REPOS: Repo[] = [
  {
    org: "asaficontact",
    name: "DKMV",
    lang: "Python",
    langColor: "var(--lbl-backend)",
    private: true,
    updated: "2d ago",
    issues: 12,
  },
  {
    org: "acme",
    name: "widgets",
    lang: "TypeScript",
    langColor: "var(--lbl-frontend)",
    private: false,
    updated: "5d ago",
    issues: 3,
  },
];

const PREFLIGHT: PreflightReport = {
  ready: true,
  checks: [
    { id: "github_token", label: "GitHub connected", sub: "present", ok: true },
    { id: "docker", label: "Docker available", sub: "27.0.0", ok: true },
  ],
  blockers: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.connectGitHub.mockResolvedValue({
    connected: true,
    token_hint: "github_pat_••••WXYZ",
    permissions: ["issues:write", "pull_requests:write", "contents:write", "metadata:read"],
  });
  mocks.listRepos.mockResolvedValue(REPOS);
  mocks.getPreflight.mockResolvedValue(PREFLIGHT);
  mocks.syncProject.mockResolvedValue(true);
});

describe("disconnected hero (AC-10, AC-11)", () => {
  it("lists the four PAT permissions verbatim", () => {
    render(<Connect onDone={vi.fn()} />);
    expect(screen.getByText("issues:write")).toBeInTheDocument();
    expect(screen.getByText("pull_requests:write")).toBeInTheDocument();
    expect(screen.getByText("contents:write")).toBeInTheDocument();
    expect(screen.getByText("metadata:read")).toBeInTheDocument();
  });

  it("shows the verbatim reassurance copy", () => {
    render(<Connect onDone={vi.fn()} />);
    expect(screen.getByText(/Nothing runs until you say so\./)).toBeInTheDocument();
  });

  it("shows the verbatim hero headline", () => {
    render(<Connect onDone={vi.fn()} />);
    expect(screen.getByText(/Turn your GitHub issues/)).toBeInTheDocument();
  });
});

describe("connect → picker (FR-01-3)", () => {
  it("stores the PAT and advances to the picker", async () => {
    render(<Connect onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/personal access token/i), {
      target: { value: "github_pat_TESTTOKENVALUE1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Connect GitHub/i }));

    await waitFor(() => expect(mocks.connectGitHub).toHaveBeenCalledWith("github_pat_TESTTOKENVALUE1234"));
    expect(await screen.findByText("Choose a repository")).toBeInTheDocument();
    expect(screen.getByText("widgets")).toBeInTheDocument();
  });

  it("disables Connect until a token is entered", () => {
    render(<Connect onDone={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Connect GitHub/i })).toBeDisabled();
  });
});

describe("picker → what-we'll-do + preflight + open (AC-12)", () => {
  it("renders repos, confirm rows and preflight, then syncs on Open project", async () => {
    const onDone = vi.fn();
    render(<Connect onDone={onDone} initialState="picker" initialRepos={REPOS} initialPreflight={PREFLIGHT} />);

    // Select a repo → the confirm rail appears.
    fireEvent.click(screen.getByRole("button", { name: "Select asaficontact/DKMV" }));

    // Three "What we'll do" confirm rows.
    expect(screen.getByText("What we'll do")).toBeInTheDocument();
    expect(screen.getByText(/Read issues from/)).toBeInTheDocument();
    expect(screen.getByText(/labels to track work/)).toBeInTheDocument();
    expect(screen.getByText("Nothing runs until you press Run")).toBeInTheDocument();

    // Preflight rows rendered.
    expect(screen.getByText("Preflight")).toBeInTheDocument();
    expect(screen.getByText("GitHub connected")).toBeInTheDocument();
    expect(screen.getByText("Docker available")).toBeInTheDocument();

    // Open project → sync called with the slug + onDone fired.
    fireEvent.click(screen.getByRole("button", { name: /Open project/i }));
    await waitFor(() => expect(mocks.syncProject).toHaveBeenCalledWith("asaficontact/DKMV"));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("asaficontact/DKMV"));
  });

  it("filters the repo list by the search query", () => {
    render(<Connect onDone={vi.fn()} initialState="picker" initialRepos={REPOS} initialPreflight={PREFLIGHT} />);
    fireEvent.change(screen.getByPlaceholderText(/Search repositories/i), {
      target: { value: "widgets" },
    });
    expect(screen.getByRole("button", { name: "Select acme/widgets" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select asaficontact/DKMV" })).not.toBeInTheDocument();
  });
});
