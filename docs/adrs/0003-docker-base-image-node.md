# Docker Base Image: node:20-bookworm

## Status

Accepted

## Context and Problem Statement

DKMV runs Claude Code inside Docker containers. The base image must provide Node.js (Claude Code's runtime), Python (for SWE-ReX), and a full package ecosystem for system tools. Which Docker base image should we use?

## Decision Drivers

- Claude Code requires Node.js 20+ runtime
- SWE-ReX requires Python 3 with pipx
- Build-essential needed for native Node modules
- Image must be reliable and reproducible across environments
- Anthropic's own devcontainer uses node:20-bookworm

## Considered Options

- `node:20-bookworm` — Debian Bookworm with Node.js 20 LTS
- `node:20-alpine` — Alpine Linux with Node.js 20 LTS
- `node:20-bookworm-slim` — Minimal Debian Bookworm with Node.js 20 LTS
- `python:3.12-bookworm` — Python-first image, install Node.js separately

## Decision Outcome

Chosen option: "node:20-bookworm", because it provides both the Node.js runtime Claude Code needs and a full Debian apt ecosystem for system packages, matching Anthropic's own recommended setup.

### Image Layer Structure

```
┌─────────────────────────────────────────────────┐
│            dkmv-sandbox:latest                   │
├─────────────────────────────────────────────────┤
│  ENV: PATH, NODE_OPTIONS=4096MB,                │
│       IS_SANDBOX=1, DISABLE_NONINTERACTIVE      │
│  USER: dkmv (UID 1000, passwordless sudo)       │
│  WORKDIR: /home/dkmv/project                    │
├─────────────────────────────────────────────────┤
│  SWE-ReX (pipx install, as dkmv user)           │
│  └── swerex-remote in ~/.local/bin              │
├─────────────────────────────────────────────────┤
│  Claude Code (npm install -g, version-pinnable) │
│  └── @anthropic-ai/claude-code in /usr/local    │
├─────────────────────────────────────────────────┤
│  System packages (single apt RUN layer):        │
│  ├── git, curl, wget, jq, openssh-client        │
│  ├── build-essential (gcc, make)                │
│  ├── python3, python3-pip, python3-venv, pipx   │
│  ├── gh CLI (from GitHub's official apt repo)   │
│  └── sudo, less, procps                         │
├─────────────────────────────────────────────────┤
│  node:20-bookworm (Debian Bookworm + Node 20)   │
│  └── glibc, apt, Node.js 20 LTS                │
└─────────────────────────────────────────────────┘
```

### Key Design Choices

- **Non-root user**: `dkmv` (UID 1000) — Claude Code's `--dangerously-skip-permissions` refuses to run as root. UID 1000 matches most host users for bind-mount volume permissions.
- **npm for Claude Code**: The native installer has an OOM bug in Docker (issue #22536) and cannot pin versions. npm install provides deterministic, cache-friendly Docker layers.
- **pipx for SWE-ReX**: Complies with PEP 668 (Debian Bookworm marks system Python as externally managed). Isolates SWE-ReX in its own venv.
- **NODE_OPTIONS=4096MB**: Claude Code idles at 400-700 MB but grows to 1-4 GB during active prompts. 4 GB matches Anthropic's own devcontainer setting.

### Consequences

- Good: Native Node modules work reliably (glibc, not musl).
- Good: Full apt ecosystem available for git, gh CLI, build-essential, Python, pipx.
- Good: Matches Anthropic's own `.devcontainer/Dockerfile` base image.
- Good: Node.js 20 LTS provides long-term support and stability.
- Bad: Larger image size (~1GB) compared to Alpine (~200MB) or slim (~400MB).
- Neutral: Python must be installed via apt (python3, python3-pip, python3-venv, pipx) since this is a Node-first image.

## Rejected Alternatives

- **Alpine**: musl libc causes subtle breakage with native Node modules. Claude Code and its dependencies may use native addons that expect glibc. The debugging difficulty outweighs the smaller image size.
- **Slim variant**: Lacks build-essential which is needed for native Node modules. Adding it back negates most size savings while adding complexity.
- **Python-first image**: Would require installing Node.js separately, adding complexity. Since Claude Code is the primary workload and requires Node.js, a Node-first image is more natural.
