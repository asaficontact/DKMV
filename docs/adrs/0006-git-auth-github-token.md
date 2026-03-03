# Git Authentication: GITHUB_TOKEN + gh auth

## Status

Accepted

## Context and Problem Statement

Components running inside Docker containers need to clone repositories, push branches, and create pull requests. How should we authenticate git operations inside the sandbox containers?

## Decision Drivers

- Must work inside ephemeral Docker containers (no persistent SSH keys)
- Must support both public and private GitHub repositories
- Must enable `gh` CLI operations (PR creation, issue comments)
- Must be simple to configure (single environment variable)
- Must not leak credentials to disk inside the container

## Considered Options

- `GITHUB_TOKEN` environment variable + `gh auth setup-git` — token-based HTTPS authentication
- SSH keys mounted as Docker volumes — key-based SSH authentication
- GitHub App installation tokens — fine-grained, short-lived tokens
- Git credential helper with hardcoded credentials

## Decision Outcome

Chosen option: "GITHUB_TOKEN + gh auth setup-git", because it provides a single environment variable that enables both git HTTPS operations and gh CLI commands without persisting secrets to disk or managing SSH key files.

### Authentication Flow

```
Host Machine                        Docker Container
┌──────────────┐                   ┌──────────────────────────┐
│ .env file    │                   │                          │
│ GITHUB_TOKEN │                   │  1. Container starts     │
│ =ghp_xxx...  │                   │     with GITHUB_TOKEN    │
└──────┬───────┘                   │     in environment       │
       │                           │                          │
       ▼                           │  2. gh auth login        │
┌──────────────┐  -e GITHUB_TOKEN  │     --with-token         │
│ DKMVConfig   │ ─────────────────►│     (stdin from env)     │
│ .github_token│   docker_args     │                          │
└──────┬───────┘                   │  3. gh auth setup-git    │
       │                           │     (configures git      │
       ▼                           │      credential helper)  │
┌──────────────┐                   │                          │
│ SandboxConfig│                   │  4. git clone / push     │
│ env_vars: {  │                   │     uses HTTPS + token   │
│  GITHUB_TOKEN│                   │     transparently        │
│ }            │                   │                          │
└──────────────┘                   │  5. gh pr create         │
                                   │     uses same token      │
                                   └──────────────────────────┘
```

### Implementation

In `ComponentRunner._setup_workspace()` (`dkmv/tasks/component.py`):

1. `SandboxManager.setup_git_auth()` runs inside the container:
   ```bash
   echo "$GITHUB_TOKEN" | gh auth login --with-token && gh auth setup-git
   ```
2. `GITHUB_TOKEN` is forwarded via `SandboxConfig.env_vars` → SWE-ReX `docker_args=["-e=GITHUB_TOKEN=..."]`
3. All subsequent `git clone`, `git push`, and `gh pr create` commands use the token transparently via the credential helper

### Security

- Token is passed as a Docker environment variable, never written to a file inside the container
- Container is ephemeral — destroyed after the component run (unless `--keep-alive`)
- All user-supplied values in shell commands (branch names, repo URLs) are protected with `shlex.quote()` to prevent injection

### Consequences

- Good: Single `GITHUB_TOKEN` env var configures both git and gh CLI authentication.
- Good: `gh auth setup-git` configures the git credential helper automatically — no manual `.gitconfig` needed.
- Good: Token is passed via Docker environment variable, never written to disk.
- Good: Works with both personal access tokens and fine-grained tokens.
- Good: gh CLI can create PRs, comment on issues, and perform API calls with the same token.
- Bad: HTTPS-only (no SSH cloning), though this is acceptable for CI/automation use cases.
- Bad: Token scope must include `repo` access for private repositories, which is broader than ideal.
- Neutral: Users must create and manage their own GitHub tokens.
