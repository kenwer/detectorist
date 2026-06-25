#!/bin/bash
set -euo pipefail
# This script guides you through the release process with confirmations at
# each step. It automates the following tasks:
#
#   1. Compile UI files
#      uv run poe compile-ui
#
#   2. Update TOCs (Table of Contents) in README.md and FAQ.md
#      ./scripts/update-TOCs.sh
#
#   3. Run linter to check code quality
#      uv run ruff check
#
#   4. Check if the working directory is clean
#      git status
#
#   5. Increment the version number in _version.py
#      sed -i "s/__version__ = .../__version__ = .../"
#
#   6. Adjust CHANGELOG.md (replace "## [Unreleased]" with the new version and date)
#      sed -i "s/## \[Unreleased\]/## [X.Y.Z] - YYYY-MM-DD/"
#
#   7. Compile QRC files (after changelog is updated, since it's embedded in resources)
#      uv run poe compile-qrc
#
#   8. Commit the changes with a message like "Bump version to 0.7.4"
#      git add ... && git commit -m "Bump version to X.Y.Z"
#
#   9. Push to remote and wait for GitHub Actions to complete
#      git push
#
#  10. Tag the release and push the tag to trigger the release workflow
#      V="0.7.4"; git tag -a "v${V}" -m "Release version ${V}" && git push -u origin "v${V}"
#
# Usage:
#   ./scripts/release.sh                         # Run the release process
#   ./scripts/release.sh --delete-tag            # Interactively select a tag to delete
#   ./scripts/release.sh --delete-tag <version>  # Delete a specific tag (e.g., 0.7.3)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# File paths
VERSION_FILE="src/detectorist/_version.py"
CHANGELOG_FILE="CHANGELOG.md"

# Helper functions
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

confirm() {
    local prompt="${1:-Continue?}"
    while true; do
        read -rp "$(echo -e "${YELLOW}?${NC} ${prompt} [Y/n]: ")" yn
        case $yn in
            [Yy]* | "" ) return 0;;
            [Nn]* ) return 1;;
            * ) echo "Please answer y or n.";;
        esac
    done
}

wait_for_enter() {
    local prompt="${1:-Press Enter to continue...}"
    read -rp "$(echo -e "${BLUE}→${NC} ${prompt}")"
}

# Handle --delete-tag option
if [[ "${1:-}" == "--delete-tag" ]]; then
    if [[ -n "${2:-}" ]]; then # Version provided as argument
        VERSION="$2"
    else
        # Show recent tags and prompt for selection
        echo ""
        info "Recent tags:"
        RECENT_TAGS=$(git tag --sort=-version:refname | head -3)
        if [[ -z "$RECENT_TAGS" ]]; then
            error "No tags found in this repository."
        fi
        LATEST_TAG=$(echo "$RECENT_TAGS" | head -1)
        echo "$RECENT_TAGS" | nl -w2 -s') '
        echo ""
        read -rp "$(echo -e "${YELLOW}?${NC} Enter tag to delete (default: ${LATEST_TAG}): ")" TAG_INPUT
        if [[ -z "$TAG_INPUT" ]]; then
            TAG="$LATEST_TAG"
        else
            TAG="$TAG_INPUT"
        fi
        # Strip 'v' prefix if present, normalize to ensure consistent format
        VERSION="${TAG#v}"
    fi
    TAG="v${VERSION}"

    echo ""
    warn "This will delete tag ${TAG} locally and from the remote."
    echo ""

    if ! confirm "Delete tag ${TAG}?"; then
        info "Cancelled."
        exit 0
    fi

    info "Deleting local tag ${TAG}..."
    if git tag -d "${TAG}"; then
        success "Local tag deleted"
    else
        warn "Local tag not found or already deleted"
    fi

    info "Deleting remote tag ${TAG}..."
    if git push origin ":${TAG}"; then
        success "Remote tag deleted"
    else
        warn "Remote tag not found or already deleted"
    fi

    echo ""
    success "Tag ${TAG} deleted!"
    exit 0
fi

# Ensure we're in the project root
if [[ ! -f "$VERSION_FILE" ]]; then
    error "Cannot find $VERSION_FILE. Please run this script from the project root."
fi

# Step 1: Compile UI files
echo ""
info "Step 1: Compiling UI files..."
uv run poe compile-ui
success "UI files compiled"

# Step 2: Update TOCs
echo ""
info "Step 2: Updating TOCs..."
if [[ -x "scripts/update-TOCs.sh" ]]; then
    ./scripts/update-TOCs.sh
    success "TOCs updated"
else
    warn "scripts/update-TOCs.sh not found or not executable, skipping..."
fi

# Step 3: Run linter
echo ""
info "Step 3: Running linter..."
if ! uv run ruff check; then
    error "Linter check failed. Please fix the issues before releasing."
fi
success "Linter check passed"

# Step 4: Check working directory
echo ""
info "Step 4: Checking working directory..."
if [[ -n $(git status --porcelain) ]]; then
    warn "Working directory is not clean:"
    git status --short
    if ! confirm "Continue anyway?"; then
        exit 1
    fi
else
    success "Working directory is clean"
fi

# Get current version
CURRENT_VERSION=$(uv run poe -q get_app_version)
info "Current version: ${GREEN}${CURRENT_VERSION}${NC}"

# Calculate version options
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
PATCH_BUMP="${MAJOR}.${MINOR}.$((PATCH + 1))"
MINOR_BUMP="${MAJOR}.$((MINOR + 1)).0"

# Prompt for new version
echo ""
info "Select new version:"
echo "  1) ${PATCH_BUMP} (patch)"
echo "  2) ${MINOR_BUMP} (minor)"
echo "  3) Enter custom version"
echo ""

while true; do
    read -rp "$(echo -e "${YELLOW}?${NC} Choose option [1/2/3] (default: 1): ")" VERSION_CHOICE
    case $VERSION_CHOICE in
        1 | "") NEW_VERSION="$PATCH_BUMP"; break;;
        2) NEW_VERSION="$MINOR_BUMP"; break;;
        3)
            while true; do
                read -rp "$(echo -e "${YELLOW}?${NC} Enter version (e.g., 1.0.0): ")" NEW_VERSION
                if [[ $NEW_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                    break
                else
                    warn "Invalid version format. Please use semver (e.g., 1.0.0)"
                fi
            done
            break;;
        *) warn "Please choose 1, 2, or 3";;
    esac
done

echo ""
info "Release plan:"
echo -e "  5. Update version: ${CURRENT_VERSION} → ${GREEN}${NEW_VERSION}${NC} in ${VERSION_FILE}"
echo -e "  6. Update CHANGELOG.md ([Unreleased] → [${NEW_VERSION}] - $(date +%Y-%m-%d))"
echo -e "  7. Compile QRC files (that includes changelog for the about dialog)"
echo -e "  8. Commit: \"Bump version to ${NEW_VERSION}\""
echo -e "  9. Push to remote and wait for CI"
echo " 10. Tag: v${NEW_VERSION}"
echo ""

if ! confirm "Proceed with release?"; then
    info "Release cancelled."
    exit 0
fi

# Step 5: Update version in _version.py
echo ""
info "Step 5: Updating version in ${VERSION_FILE}..."
sed -i.bak "s/__version__ = \"${CURRENT_VERSION}\"/__version__ = \"${NEW_VERSION}\"/" "$VERSION_FILE"
rm -f "${VERSION_FILE}.bak"
success "Version updated to ${NEW_VERSION}"

# Step 6: Update CHANGELOG.md
echo ""
info "Step 6: Updating CHANGELOG.md..."
TODAY=$(date +%Y-%m-%d)
sed -i.bak "s/## \[*[Uu]nreleased\]*/## [${NEW_VERSION}] - ${TODAY}/" "$CHANGELOG_FILE"
rm -f "${CHANGELOG_FILE}.bak"
success "CHANGELOG.md updated"

# Step 7: Compile QRC files (after changelog is updated, since it's embedded in resources)
echo ""
info "Step 7: Compiling QRC files..."
uv run poe compile-qrc
success "QRC files compiled"

# Show diff for review
echo ""
info "Review changes:"
git diff --color=always

echo ""
info "Files that will be staged:"
git status --short
echo ""

if ! confirm "Stage and commit these changes?"; then
    warn "Rolling back file changes..."
    git checkout -- "$VERSION_FILE" "$CHANGELOG_FILE" README.md FAQ.md src/detectorist/resources_rc.py 2>/dev/null || true
    info "Changes rolled back."
    if ! confirm "Continue with remaining steps (push, tag) using existing commits?"; then
        info "Release cancelled."
        exit 1
    fi
fi

# Step 8: Commit changes
echo ""
info "Step 8: Staging and committing changes..."
git add "$VERSION_FILE" "$CHANGELOG_FILE" README.md FAQ.md src/detectorist/resources_rc.py

echo ""
info "Staged files:"
git diff --cached --name-only | sed 's/^/  • /'
echo ""
info "Commit message: \"Bump version to ${NEW_VERSION}\""
echo ""

if ! confirm "Create this commit?"; then
    warn "Unstaging changes..."
    git reset HEAD -- "$VERSION_FILE" "$CHANGELOG_FILE" README.md FAQ.md src/detectorist/resources_rc.py
    info "Commit cancelled. Files are still modified but not committed."
    if ! confirm "Continue with remaining steps (push, tag)?"; then
        info "Release cancelled."
        exit 1
    fi
fi

git commit -m "Bump version to ${NEW_VERSION}"
success "Changes committed"

# Step 9: Push to remote
echo ""
REMOTE_URL=$(git remote get-url origin)
CURRENT_BRANCH=$(git branch --show-current)
info "Step 9: Push to remote"
echo ""
info "This will push:"
echo "  • Branch: ${CURRENT_BRANCH}"
echo "  • Remote: ${REMOTE_URL}"
echo ""
info "Commits to be pushed:"
git log --oneline origin/${CURRENT_BRANCH}..HEAD | sed 's/^/  • /'
echo ""

if ! confirm "Push these commits to ${CURRENT_BRANCH}?"; then
    warn "Push cancelled. Commit exists locally but not pushed."
    info "You can push manually with: git push"
    if ! confirm "Continue with tagging step?"; then
        info "Release cancelled."
        exit 1
    fi
fi

git push
success "Pushed to remote"

echo ""
info "Waiting for CI to complete..."
REPO_PATH=$(echo "$REMOTE_URL" | sed 's|.*github\.com[:/]||; s/\.git$//')
COMMIT_SHA=$(git rev-parse HEAD)
API_URL="https://api.github.com/repos/${REPO_PATH}/actions/runs?head_sha=${COMMIT_SHA}"
info "Checking: curl -s '${API_URL}' | jq -r '.workflow_runs[0].status'"

while true; do
    RESPONSE=$(curl -s "$API_URL")

    # Check for rate limit error
    if echo "$RESPONSE" | jq -e '.message | test("rate limit")' >/dev/null 2>&1; then
        warn "GitHub API rate limit exceeded"
        info "Check CI status manually: https://github.com/${REPO_PATH}/actions"
        if ! confirm "Continue with tagging step?"; then
            info "Release cancelled."
            exit 1
        fi
        break
    fi

    STATUS=$(echo "$RESPONSE" | jq -r '.workflow_runs[0].status // empty')
    CONCLUSION=$(echo "$RESPONSE" | jq -r '.workflow_runs[0].conclusion // empty')

    if [[ -z "$STATUS" ]]; then
        echo "  Waiting for workflow to start..."
        sleep 10
        continue
    fi

    if [[ "$STATUS" == "completed" ]]; then
        if [[ "$CONCLUSION" == "success" ]]; then
            success "CI passed!"
            break
        else
            error "CI failed! Check: https://github.com/${REPO_PATH}/actions"
        fi
    fi

    echo "  Status: ${STATUS}..."
    sleep 30
done

# Step 10: Create and push tag
echo ""
info "Step 10: Create and push tag"
echo ""
info "This will create:"
echo "  • Tag: v${NEW_VERSION}"
echo "  • Message: \"Release version ${NEW_VERSION}\""
echo "  • At commit: $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
echo ""

if ! confirm "Create this tag?"; then
    warn "Tag creation cancelled."
    info "You can create the tag manually with: git tag -a \"v${NEW_VERSION}\" -m \"Release version ${NEW_VERSION}\""
    info "Release cancelled."
    exit 1
fi

git tag -a "v${NEW_VERSION}" -m "Release version ${NEW_VERSION}"
success "Tag created locally"

echo ""
info "This will push tag v${NEW_VERSION} to origin"
echo ""

if ! confirm "Push tag to remote?"; then
    warn "Tag push cancelled. Tag exists locally but not pushed."
    info "You can push manually with: git push -u origin \"v${NEW_VERSION}\""
    info "Release partially complete (tag not pushed)."
    exit 1
fi

git push -u origin "v${NEW_VERSION}"
success "Tag pushed"

echo ""
success "Tag v${NEW_VERSION} pushed!"
echo ""
info "Next steps:"
echo " - Watch the release workflow: https://github.com/$(git remote get-url origin | sed 's|.*github\.com[:/]||; s/\.git$//')/actions"
echo " - Once complete, check the tag: https://github.com/$(git remote get-url origin | sed 's|.*github\.com[:/]||; s/\.git$//')/releases/tag/v${NEW_VERSION}"
echo " - You may want to create a release from the tag: https://github.com/$(git remote get-url origin | sed 's|.*github\.com[:/]||; s/\.git$//')/releases/new?tag=v${NEW_VERSION}"
echo ""
