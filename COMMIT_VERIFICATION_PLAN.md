# Simulation Commit Verification Plan

This document outlines a read-only verification process for simulation commits in the Federation project. The verification ensures commit integrity, security, and compliance with project constraints without modifying the source code.

## Prerequisites

- Access to the Git repository containing the simulation code
- Basic Git command-line knowledge
- List of forbidden file patterns (e.g., `.env`, `.secrets`, `*.key`, `*_credentials.*`)
- List of allowed directories (e.g., `.kilo/state/`, `docs/`, `scripts/`)

## Verification Steps

### 1. Commit Signature Verification
Verify the commit is cryptographically signed by an authorized developer.

```bash
# Verify commit signature (if signed commits are used)
git verify-signature <commit-hash>

# Check exit code: 0 = good signature, non-zero = bad or missing signature
if [ $? -ne 0 ]; then
  echo "ERROR: Commit signature verification failed"
  exit 1
fi
```

### 2. Forbidden Files Check
Ensure no forbidden files are included in the commit.

```bash
# Get list of files changed in the commit
FILES_CHANGED=$(git diff-tree --no-commit-id --name-only -r <commit-hash>)

# Define forbidden patterns (customize as needed)
FORBIDDEN_PATTERNS=(
  "*.env"
  "*.secrets"
  "*.key"
  "*_credentials.*"
  "*.p12"
  "*.pfx"
)

# Check each file against forbidden patterns
for file in $FILES_CHANGED; do
  for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
    if [[ $file == $pattern ]]; then
      echo "ERROR: Forbidden file detected: $file"
      exit 1
    fi
  done
done
```

### 3. Allowed Directories Check
Verify all changes are confined to permitted directories.

```bash
# Get list of files changed in the commit
FILES_CHANGED=$(git diff-tree --no-commit-id --name-only -r <commit-hash>)

# Define allowed directories (customize as needed)
ALLOWED_DIRS=(
  ".kilo/state/"
  "docs/"
  "scripts/"
  "src/federation/simulation/"
)

# Function to check if path is within allowed directories
is_allowed() {
  local path="$1"
  for dir in "${ALLOWED_DIRS[@]}"; do
    if [[ $path == $dir* ]]; then
      return 0
    fi
  done
  return 1
}

# Check each changed file
for file in $FILES_CHANGED; do
  if ! is_allowed "$file"; then
    echo "ERROR: File outside allowed directories: $file"
    echo "Allowed directories: ${ALLOWED_DIRS[*]}"
    exit 1
  fi
done
```

### 4. Additional Checks (Optional)
Depending on project requirements, consider these additional read-only checks:

#### File Size Limits
```bash
# Check for unusually large files that might indicate binary blobs
for file in $FILES_CHANGED; do
  size=$(git show <commit-hash>:"$file" | wc -c)
  if [ $size -gt 1048576 ]; then  # 1MB limit
    echo "WARNING: Large file detected: $file ($size bytes)"
  fi
done
```

#### Binary File Detection
```bash
# Prevent accidental binary commits in text-only repositories
for file in $FILES_CHANGED; do
  if git show <commit-hash>:"$file" | file - | grep -q "data"; then
    echo "WARNING: Binary file detected: $file"
  fi
done
```

### 5. Verification Summary
If all checks pass, output success confirmation.

```bash
echo "SUCCESS: Commit <commit-hash> passed all verification checks"
echo "Verified at: $(date)"
echo "Verified by: $(git config user.name)"
```

## Implementation Notes for Polecats

1. **Read-Only Operations**: All verification commands use `git show`, `git diff-tree`, and `git verify-signature` which do not modify the working directory or repository state.

2. **Error Handling**: The script exits immediately on any verification failure with a clear error message.

3. **Customization**: 
   - Update `FORBIDDEN_PATTERNS` array with project-specific forbidden file patterns
   - Update `ALLOWED_DIRS` array with project-specific allowed directories
   - Adjust file size limits and additional checks as needed

4. **Execution Context**: 
   - Run verification in a clean workspace or temporary clone
   - Ensure you have fetched the commit to be verified (`git fetch origin <commit-hash>`)
   - Verification can be performed on any branch as long as the commit is accessible

5. **Integration**: This plan can be implemented as a shell script or integrated into CI/CD pipelines for automated commit verification.

## Example Usage

```bash
# Fetch the commit to verify (replace with actual commit hash)
git fetch origin abc123def456

# Run verification
./verify_commit.sh abc123def456
```

## References

- Git documentation: `git help verify-signature`
- Git documentation: `git help diff-tree`
- Project-specific security policies (refer to GOVERNANCE.md and COVENANT.md)