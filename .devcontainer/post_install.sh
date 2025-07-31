#!/bin/bash
set -ex

# Install package
sudo su - vscode bash -c "cd /workspaces/unleash-python-sdk; pip install -U -r requirements.txt; python -m build; ./scripts/get-spec.sh;"

# Install pre-config
pip install pre-commit
pre-commit install
pre-commit

# Woohoo!
echo "Hooray, it's done!"
