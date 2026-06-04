#!/usr/bin/env sh
set -eu

git config core.hooksPath .githooks
echo "Git hooks enabled for this repository: core.hooksPath=.githooks"
