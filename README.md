## Introduction

This library implements the client part of the INDICATE data exchange protocol which is used by data providers for submitting quality indicator results and retrieving aggregated quality indicator results for display in the dashboard.

## Requirements.

* Python >= 3.10

* API-level access to the INDICATE Hub which provides the server part

## Usage

This library can be used in applications such as the INDICATE quality indicator dashboard and the INDICATE data exchange client for data providers.

## Code Generation

The directory `openapi-generation` contains the OpenAPI definition of the data exchange protocol and the configuration for the code generator.
To regenerate the code of this library for a new version of the protocol

1. Copy the new OpenAPI definition to `openapi-generation/api.yaml`

2. Run `cd openapi-generation ; ./generate.sh`

3. Test the generated code

4. Commit all changes
