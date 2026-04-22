#!/bin/bash

# Configure pip to use internal Artifactory (for any pip install calls inside the container)
mkdir -p ~/.pip
cat > ~/.pip/pip.conf << EOF
[global]
index-url = https://artifactory.internal.cba/api/pypi/pypi/simple
EOF

echo "pip configuration updated to use internal artifactory"

# Configure uv to use internal Artifactory (for uv add / uv pip install inside the container)
mkdir -p ~/.config/uv
cat > ~/.config/uv/uv.toml << EOF
index-url = "https://artifactory.internal.cba/artifactory/api/pypi/org.python.pypi/simple"

[pip]
index-url = "https://artifactory.internal.cba/artifactory/api/pypi/org.python.pypi/simple"
EOF

echo "uv configuration updated to use internal artifactory"

# Set necessary claude code configurations
npm config set registry https://artifactory.internal.cba/api/npm/npm/
npm install -g @anthropic-ai/claude-code
