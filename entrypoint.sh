#!/bin/bash
set -e

if [ -n "$OUTPUT_REPO_URL" ] && [ ! -d /workspace/output-repo/.git ]; then
    echo "Cloning output repo: $OUTPUT_REPO_URL"
    git clone "$OUTPUT_REPO_URL" /workspace/output-repo
fi

exec python /workspace/server.py
