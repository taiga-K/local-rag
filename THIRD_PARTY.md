# Third-party notices

Versions below are the ones installed for the unit-test environment on 2026-11-17, except the container images and the optional embed extra. Commercial use is allowed for each license named here.

## Python packages

| Package | Version | SPDX |
| --- | --- | --- |
| fastapi | 0.163.1 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| psycopg | 3.3.9 | LGPL-3.0-only |
| psycopg-binary | 3.3.9 | LGPL-3.0-only |
| redis | 8.1.0 | MIT |
| qdrant-client | 1.20.0 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| sudachipy | 0.7.0 | Apache-2.0 |
| sudachidict-core | 20261015 | Apache-2.0 |
| beautifulsoup4 | 4.15.0 | MIT |
| pytest | 9.2.0 | MIT |

`sentence-transformers` is the optional extra `embed`. It is not imported by the unit tests. Its license is Apache-2.0. The API image installs it at build time. The embedding model `cl-nagoya/ruri-v3-310m` is Apache-2.0.

`psycopg` is LGPL-3.0-only. It is the driver named by the design. The package is used as a library and is not modified here.

## Container images

| Image | SPDX of the server |
| --- | --- |
| postgres:16-alpine | PostgreSQL |
| redis:7.2-alpine | BSD-3-Clause |
| qdrant/qdrant:v1.15.0 | Apache-2.0 |
| python:3.12-slim | PSF-2.0 |

`redis:7.2-alpine` tracks Redis 7.2.x. Redis 7.4 and later are not used.
