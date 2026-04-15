#!/usr/bin/env bash
set -e

VERSION=${1:-1.0.0}
IMAGE=physical-api

echo "Building ${IMAGE}:${VERSION}"
docker build --no-cache -t ${IMAGE}:${VERSION} .

