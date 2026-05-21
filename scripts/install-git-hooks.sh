#!/usr/bin/env bash
# scripts/install-git-hooks.sh
#
# Installs repo-versioned git hooks into the local .git/hooks directory.
# Run once after cloning, or re-run after pulling hook updates.
#
# Usage:
#   bash scripts/install-git-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
VERSIONED_PRE_COMMIT_HOOK="$REPO_ROOT/scripts/hooks/pre-commit"
VERSIONED_PRE_PUSH_HOOK="$REPO_ROOT/scripts/hooks/pre-push"

echo "Installing git hooks from scripts/hooks/ ..."

# ── pre-commit ───────────────────────────────────────────────────────────────

TARGET="$HOOKS_DIR/pre-commit"

if [ -f "$TARGET" ] && [ ! -L "$TARGET" ]; then
    BACKUP="$TARGET.bak.$(date +%s)"
    echo "  Existing $TARGET is not a symlink — backing up to $BACKUP"
    mv "$TARGET" "$BACKUP"
fi

# Make versioned scripts executable
chmod +x "$VERSIONED_PRE_COMMIT_HOOK"
chmod +x "$REPO_ROOT/scripts/hooks/pre-commit-check.sh"
chmod +x "$VERSIONED_PRE_PUSH_HOOK"
chmod +x "$REPO_ROOT/scripts/hooks/pre-push-check.sh"

# Install as symlink so updates to the repo script apply immediately
ln -sf "$VERSIONED_PRE_COMMIT_HOOK" "$TARGET"

echo "  Installed: .git/hooks/pre-commit -> scripts/hooks/pre-commit"

# ── pre-push ─────────────────────────────────────────────────────────────────

TARGET="$HOOKS_DIR/pre-push"

if [ -f "$TARGET" ] && [ ! -L "$TARGET" ]; then
    BACKUP="$TARGET.bak.$(date +%s)"
    echo "  Existing $TARGET is not a symlink — backing up to $BACKUP"
    mv "$TARGET" "$BACKUP"
fi

ln -sf "$VERSIONED_PRE_PUSH_HOOK" "$TARGET"

echo "  Installed: .git/hooks/pre-push -> scripts/hooks/pre-push"

echo ""
echo "Done. Active hooks:"
ls -la "$HOOKS_DIR" | grep -v sample | grep -v "^total" | grep -v "^d"
