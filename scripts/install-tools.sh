#!/usr/bin/env bash
set -euo pipefail

echo "Prerequisites: Go 1.20+ for nuclei/dalfox; Python 3.9+ and pip for sqlmap."

if command -v go >/dev/null 2>&1; then
  echo "Installing projectdiscovery / dalfox scanners via Go..."
  go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
  go install github.com/hahwul/dalfox/v2@latest
else
  echo "go not found; install Go first, then re-run this script."
fi

if command -v python >/dev/null 2>&1; then
  python -m pip install sqlmap
elif command -v pip >/dev/null 2>&1; then
  pip install sqlmap
else
  echo "python/pip not found; install Python first, then run: pip install sqlmap"
fi

echo "Ensure \$(go env GOPATH)/bin is on PATH, or re-run module install in the app so it registers the tool path."
