# =============================================================================
# DKMV Sandbox Dockerfile
# =============================================================================
#
# Purpose: Builds an isolated container for running Claude Code as an AI coding
# agent, with SWE-ReX for remote command execution. Designed to be started by
# the DKMV orchestrator on the host.
#
# Build:
#   docker build -t dkmv-sandbox .
#   docker build -t dkmv-sandbox --build-arg CLAUDE_CODE_VERSION=1.0.20 .
#
# Run (from host orchestrator):
#   docker run -it --rm \
#     --memory=8g --memory-swap=8g \
#     -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
#     -p 8000:8000 \
#     dkmv-sandbox
#
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Base image
# ---------------------------------------------------------------------------
# node:20-bookworm is Anthropic's recommended base for Claude Code containers.
# It ships Node.js 20 LTS on Debian Bookworm, which gives us both the Node
# runtime Claude Code needs and a full apt ecosystem for system packages.
# We intentionally avoid Alpine (musl libc causes subtle breakage with native
# Node modules) and slim variants (we need build-essential anyway).
FROM node:20-bookworm

# ---------------------------------------------------------------------------
# Build arguments
# ---------------------------------------------------------------------------
# CLAUDE_CODE_VERSION: Pin the exact Claude Code version for reproducible
# builds. The native installer (install.sh) does NOT support version pinning,
# so we use npm even though it is "deprecated" in docs. npm install still
# works and is the only method that allows `@anthropic-ai/claude-code@X.Y.Z`.
# Set to "latest" for rolling builds, or pin like "1.0.20" for production.
#
# Rationale for npm over native installer:
#   - Native installer has an OOM bug when run from / in Docker (issue #22536)
#   - Native installer cannot pin versions (no --version flag)
#   - npm install produces deterministic, cache-friendly Docker layers
#   - Anthropic's own .devcontainer/Dockerfile still uses npm install
ARG CLAUDE_CODE_VERSION=2.1.47
ARG CODEX_VERSION=0.110.0

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
# Install everything in a single RUN to minimize layers.
#
# Core tools:
#   git              - version control (Claude Code requires it)
#   curl, wget       - HTTP clients for installers and API calls
#   jq               - JSON processing (used by Claude Code internals)
#   sudo             - needed so the non-root user can escalate when required
#   openssh-client   - git clone over SSH, gh auth
#   less, procps     - terminal usability (less for pager, ps for debugging)
#
# Build tools:
#   build-essential  - gcc, make, etc. for native Node modules
#
# Search & file tools (used by both Claude Code and Codex agents):
#   ripgrep          - fast regex search (Codex requires rg on PATH)
#   fd-find          - fast file finder (Debian installs as fdfind; symlinked to fd)
#   bat              - syntax-highlighted cat (Debian installs as batcat; symlinked to bat)
#   fzf              - fuzzy finder for interactive selection
#
# Python stack:
#   python3, python3-pip, python3-venv, pipx
#   Required for SWE-ReX and any Python-based tooling Claude might use.
#   pipx isolates CLI tools in their own venvs (PEP 668 compliance).
#
# GitHub CLI (gh):
#   Installed from GitHub's official apt repository for Debian.
#   The Debian-packaged version is too old and has broken API calls.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        wget \
        jq \
        build-essential \
        openssh-client \
        sudo \
        less \
        procps \
        ripgrep \
        fd-find \
        bat \
        fzf \
        python3 \
        python3-pip \
        python3-venv \
        pipx \
        ca-certificates \
        gnupg \
    # -- GitHub CLI: add official apt repo --
    && mkdir -p -m 755 /etc/apt/keyrings \
    && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    # -- Cleanup to reduce image size --
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Debian renames fd→fdfind and bat→batcat to avoid package name clashes.
# Both Codex and Claude Code expect the standard names on PATH.
RUN ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && ln -s /usr/bin/batcat /usr/local/bin/bat

# ---------------------------------------------------------------------------
# Claude Code installation (as root, before USER switch)
# ---------------------------------------------------------------------------
# We install globally via npm so it is available to all users.
# Version pinning: use --build-arg CLAUDE_CODE_VERSION=X.Y.Z at build time.
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# ---------------------------------------------------------------------------
# Codex CLI installation (as root, before USER switch)
# ---------------------------------------------------------------------------
# Install Codex CLI globally. Version is pinned via --build-arg CODEX_VERSION.
RUN npm install -g @openai/codex@${CODEX_VERSION}

# ---------------------------------------------------------------------------
# Non-root user: dkmv
# ---------------------------------------------------------------------------
# Claude Code's --dangerously-skip-permissions refuses to run as root for
# safety. We create a dedicated user with:
#   - UID/GID 1000 (matches most host users for volume permissions)
#   - A home directory at /home/dkmv
#   - Passwordless sudo (needed for apt install, port binding, etc.)
#   - bash as default shell
#
# IMPORTANT: node:20-bookworm already has a "node" user at UID/GID 1000.
# We must remove it first, then create our "dkmv" user at the same UID so
# that bind-mounted volumes from the host have correct permissions.
RUN userdel --remove node \
    && groupadd --gid 1000 dkmv \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash dkmv \
    && echo "dkmv ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dkmv \
    && chmod 0440 /etc/sudoers.d/dkmv

# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------
# /home/dkmv/workspace - cloned repo (created at runtime by BaseComponent)
# /home/dkmv/.claude   - Claude Code config/state directory
RUN mkdir -p /home/dkmv/workspace /home/dkmv/.claude /home/dkmv/.codex \
    && printf 'web_search = "live"\n\n[sandbox_workspace_write]\nnetwork_access = true\n' \
       > /home/dkmv/.codex/config.toml \
    && chown -R dkmv:dkmv /home/dkmv

# ---------------------------------------------------------------------------
# Claude Code onboarding bypass
# ---------------------------------------------------------------------------
# When using CLAUDE_CODE_OAUTH_TOKEN for subscription-based auth, Claude Code
# still prompts for the interactive onboarding wizard unless this file exists.
# See: https://github.com/anthropics/claude-code/issues/8938
RUN echo '{"hasCompletedOnboarding":true}' > /home/dkmv/.claude.json \
    && chown dkmv:dkmv /home/dkmv/.claude.json

# ---------------------------------------------------------------------------
# Switch to non-root user
# ---------------------------------------------------------------------------
USER dkmv

# ---------------------------------------------------------------------------
# SWE-ReX installation (as dkmv user)
# ---------------------------------------------------------------------------
# SWE-ReX must be installed AFTER the USER switch because pipx installs into
# ~/.local/. Installing as root would put binaries in /root/.local/ which the
# dkmv user cannot access.
#
# pipx install creates an isolated venv for swe-rex and puts the swerex-remote
# binary into ~/.local/bin/. The ensurepath command adds ~/.local/bin to PATH
# in the user's shell profile, but since Dockerfile ENV is more reliable for
# Docker, we also set PATH explicitly below.
RUN pipx install swe-rex \
    && pipx ensurepath

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

# PATH: Ensure the dkmv user can find:
#   - pipx-installed binaries (~/.local/bin, includes swerex-remote)
#   - npm global binaries (/usr/local/bin, already in default PATH)
#   - Standard system paths
ENV PATH="/home/dkmv/.local/bin:${PATH}"

# NODE_OPTIONS: Prevent Node.js OOM crashes.
# Claude Code idles at 400-700 MB but grows to 1-4 GB during active prompts.
# Subprocess stdout/stderr is retained in the JS heap, causing linear growth.
# 4096 MB (4 GB) matches Anthropic's own devcontainer setting.
# The Docker container should be started with --memory=8g to give headroom
# for the OS, Python, git, and other processes alongside Node.
ENV NODE_OPTIONS="--max-old-space-size=4096"

# IS_SANDBOX: Tells Claude Code this is a sandboxed environment.
# This serves two purposes:
#   1. Allows --dangerously-skip-permissions to work even if somehow run as
#      root (bypasses the root user check)
#   2. Signals to Claude Code that destructive operations are acceptable
#      because the environment is disposable
ENV IS_SANDBOX=1

# CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK: When running headless (no TTY),
# Claude Code may refuse to start. This disables that check.
ENV CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1

# CODEX_UNSAFE_ALLOW_NO_SANDBOX: Tells Codex CLI to skip Landlock/seccomp
# sandbox initialization. Docker provides container-level isolation, making
# Codex's internal Landlock sandbox redundant. Without this, Codex panics
# with LandlockRestrict because Docker doesn't expose Landlock kernel APIs.
ENV CODEX_UNSAFE_ALLOW_NO_SANDBOX=1

# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------
# Set to /home/dkmv/workspace where BaseComponent clones repos at runtime.
# This means `dkmv attach` drops users directly into the code directory.
WORKDIR /home/dkmv/workspace

# ---------------------------------------------------------------------------
# Default command
# ---------------------------------------------------------------------------
# By default, start an interactive bash shell. The host orchestrator will
# typically override this with a specific command like:
#   claude --dangerously-skip-permissions -p "your prompt here"
# or:
#   swerex-remote --auth-token <token>
CMD ["/bin/bash"]
