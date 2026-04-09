#!/usr/bin/env bash
# scripts/hooks/pre-push-check.sh
#
# Versioned pre-push logic. Called by scripts/hooks/pre-push (and via
# .git/hooks/pre-push after running scripts/install-git-hooks.sh).
#
# Blocks push when:
#   - at least one staged/committed file outside docs/, .git/, and
#     the hook/install scripts themselves has changed
#   - AND docs/PROGRESS.md has NOT been updated in the same commit range
#
# Override: git push --no-verify

set -euo pipefail

REMOTE="$1"
URL="$2"

# ── Determine commit range ──────────────────────────────────────────────────
#
# pre-push receives lines on stdin: <local-ref> <local-sha1> <remote-ref> <remote-sha1>
# We collect all pushed SHAs and build a range against their remote counterparts.

RANGE_ARGS=()
while read -r local_ref local_sha remote_ref remote_sha; do
    # Skip branch deletions
    if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then
        continue
    fi
    # New branch with no upstream — compare against empty tree
    if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
        RANGE_ARGS+=("$(git hash-object -t tree /dev/null)..${local_sha}")
    else
        RANGE_ARGS+=("${remote_sha}..${local_sha}")
    fi
done

# Nothing being pushed (e.g. tags-only or deletions-only)
if [ ${#RANGE_ARGS[@]} -eq 0 ]; then
    exit 0
fi

# ── Collect changed files across all ranges ─────────────────────────────────

ALL_CHANGED=$(git diff --name-only "${RANGE_ARGS[@]}" 2>/dev/null || true)

if [ -z "$ALL_CHANGED" ]; then
    exit 0
fi

# ── Classify changes ─────────────────────────────────────────────────────────
#
# Exempt paths (changes here never trigger the barrier):
#   docs/          — documentation layer (the required update target)
#   scripts/hooks/ — the hook scripts themselves
#   scripts/install-git-hooks.sh

EXEMPT_PATTERN="^docs/|^scripts/hooks/|^scripts/install-git-hooks\.sh"

CODE_CHANGED=$(echo "$ALL_CHANGED" | grep -vE "$EXEMPT_PATTERN" || true)
PROGRESS_CHANGED=$(echo "$ALL_CHANGED" | grep -E "^docs/PROGRESS\.md$" || true)

# ── Decision ─────────────────────────────────────────────────────────────────

if [ -n "$CODE_CHANGED" ] && [ -z "$PROGRESS_CHANGED" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  pre-push barrier: docs/PROGRESS.md not updated                 ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║                                                                  ║"
    echo "║  Non-doc files were changed but docs/PROGRESS.md was not        ║"
    echo "║  updated in this push range.                                     ║"
    echo "║                                                                  ║"
    echo "║  Changed non-doc files detected:                                 ║"
    echo "$CODE_CHANGED" | head -10 | sed 's/^/║    /'
    echo "║                                                                  ║"
    echo "║  Required action:                                                ║"
    echo "║    Update docs/PROGRESS.md and include it in your commit,       ║"
    echo "║    then push again.                                              ║"
    echo "║                                                                  ║"
    echo "║  To bypass (intentional override only):                         ║"
    echo "║    git push --no-verify                                          ║"
    echo "║                                                                  ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi

exit 0
