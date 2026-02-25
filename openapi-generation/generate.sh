#!/bin/bash

podman run --rm                                \
  -v ./api.yaml:/api.yaml:ro                   \
  -v ./options.yaml:/options.yaml:ro           \
  -v ./..:/output/                             \
  docker.io/openapitools/openapi-generator-cli \
    generate                                   \
    -g python -c /options.yaml                 \
    -i /api.yaml -o /output/
