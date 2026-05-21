#!/usr/bin/env bash
# scripts/hooks/pre-commit-check.sh
#
# Local staged-change documentation barrier.
#
# Blocks commit when:
#   - at least one staged file outside docs/, .git/, and hook/install scripts
#     has changed
#   - AND docs/PROGRESS.md is not staged in the same commit
#
# This is a minimum audit-log barrier. It does not replace the semantic
# documentation-impact rule in docs/CODER_WORKING_RULES.md.
#
# Override: git commit --no-verify

set -euo pipefail

ALL_CHANGED=$(git diff --cached --name-only --diff-filter=ACMRTUXB)

if [ -z "$ALL_CHANGED" ]; then
    exit 0
fi

EXEMPT_PATTERN="^docs/|^scripts/hooks/|^scripts/install-git-hooks\.sh"

NON_DOC_CHANGED=$(echo "$ALL_CHANGED" | grep -vE "$EXEMPT_PATTERN" || true)
PROGRESS_CHANGED=$(echo "$ALL_CHANGED" | grep -E "^docs/PROGRESS\.md$" || true)

if [ -n "$NON_DOC_CHANGED" ] && [ -z "$PROGRESS_CHANGED" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  pre-commit barrier: docs/PROGRESS.md not staged                ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║                                                                  ║"
    echo "║  Non-doc files are staged, but docs/PROGRESS.md is not staged.  ║"
    echo "║  Every non-doc change needs a documentation-impact check and    ║"
    echo "║  at minimum a progress/audit-log update in the same commit.     ║"
    echo "║                                                                  ║"
    echo "║  Staged non-doc files detected:                                  ║"
    echo "$NON_DOC_CHANGED" | head -10 | sed 's/^/║    /'
    echo "║                                                                  ║"
    echo "║  Required action:                                                ║"
    echo "║    Stage docs/PROGRESS.md, and update any affected source docs. ║"
    echo "║                                                                  ║"
    echo "║  To bypass (intentional override only):                         ║"
    echo "║    git commit --no-verify                                        ║"
    echo "║                                                                  ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi

exit 0
