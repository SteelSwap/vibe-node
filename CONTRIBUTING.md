# Contributing to vibe-node

This is a vibe-coded Cardano node. Every commit tells the story of how AI-assisted development can produce spec-compliant infrastructure. These guidelines ensure the process stays transparent, the code stays correct, and the vibes stay immaculate.

## Development Setup

```bash
# Clone with submodules (Haskell reference code in vendor/)
git clone --recursive https://github.com/SteelSwap/vibe-node.git
cd vibe-node

# Install dependencies (requires Python 3.14+)
uv sync --dev

# Build VRF native extension
uv run python -m vibe.cardano.crypto.vrf_native

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest -x -q
```

## Code Style

Enforced by **ruff** (lint + isort) and **black** (format). Line length: 99.

```bash
# Check
uv run ruff check src/ packages/ tests/
uv run black --check src/ packages/ tests/

# Fix
uv run ruff check --fix src/ packages/ tests/
uv run black src/ packages/ tests/
```

Pre-commit hooks run these automatically on staged files. CI fails on violations.

See `docs/reference/code-style.md` for detailed conventions.

## Branch Policy

**Never commit directly to main.** All work goes through branches and PRs.

- One branch per module: `m<phase>.<module>-<description>` (e.g., `m6.11-ci-quality-gates`)
- Push to your branch, open a PR for review
- Only Elder Millenial merges to main

**Never use worktrees then manually copy files.** If work from one branch depends on another, rebase or merge the dependency branch.

## Commit Messages

Every AI-assisted commit must include:

1. A clear message describing what changed and why
2. The prompt or task context that drove the change
3. A `Co-Authored-By` tag identifying the AI model

```
feat: implement chain-sync client state machine

Prompt: Implement the chain-sync client following the Ouroboros
network spec, using a typed state machine pattern for protocol
state transitions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

This is a challenge requirement — 90% of commits must include the model name and Co-Authored-By tag. The git history IS the proof that this node was vibe-coded.

## Dependencies

- Use `cbor2pure` (pure Python), never `cbor2` directly (buggy C bindings)
- Minimize new dependencies — every dep is attack surface
- Never commit keys, credentials, or signing keys
- Forked deps live in `vendor/` as git submodules

## Testing

```bash
# Full suite
uv run pytest -x -q

# Specific subsystem
uv run pytest packages/vibe-cardano/tests/consensus/ -v

# Benchmarks
uv run pytest tests/benchmarks/ --benchmark-only
```

The gold standard is **conformance tests against the Haskell node**. If the spec and the Haskell node disagree, the Haskell node is the oracle of truth.

## Spec Consultation

Every implementation step follows this loop:

1. **Consult the spec** — `vibe-node db search` for relevant sections
2. **Implement against the spec** — include spec references in comments
3. **Test against the Haskell node** — use the devnet Docker Compose
4. **Document gaps** — any divergence goes in `docs/specs/gap-analysis.md`

## PR Process

1. Create a feature branch from `main`
2. Implement, test, commit (with Co-Authored-By tags)
3. Push and open a PR
4. CI must pass (tests + lint)
5. Elder Millenial reviews and merges
