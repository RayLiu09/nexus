# NEXUS Console dependency security task package

## Task name

Console production dependency vulnerability remediation.

## Source context

- `WORKFLOWS.md`: bounded task package and verification evidence.
- `SPEC.md` and Prototype v2.2: preserve Console login, role access, and P0 flows.
- Production `npm audit --omit=dev` on `nexus-console:prod`: six affected packages.

## Goal

Resolve the reported production dependency vulnerabilities without breaking the Console build or its existing user flows.

## Scope

- `nexus-console/package.json` and `nexus-console/package-lock.json`.
- Console tests and middleware compatibility changes only if required by the dependency update.
- Rebuild and inspect the `nexus-console:prod` image after verification.

## Out of scope

- Backend dependencies, data model, and API contract changes.
- Deployment or restart of running services.
- Unrelated dependency upgrades or UI redesign.

## Forbidden changes

- Do not weaken login, role routing, API authorization, or audit behavior.
- Do not add enterprise IAM, an AI gateway, or P1/P2 functionality.

## Deliverables and acceptance

- Updated direct dependency version and reproducible lockfile.
- Production `npm audit --omit=dev` reports no vulnerabilities.
- TypeScript, relevant tests, and production build pass.
- Login/role routing and representative Console pages remain functional.
- Record the resulting image ID and any remaining limitations in the task closeout.

## Review gates

- Frontend UX Gate: login and primary Console routes render with unchanged navigation behavior.
- Permission And Audit Gate: middleware and authenticated API behavior retain their current checks; no contract changes.

## Verification evidence

- `npm audit --omit=dev --registry=https://registry.npmjs.org`: 0 vulnerabilities.
- `npm run typecheck`: passed.
- `npm run test -- --maxWorkers=2`: 58 files and 321 tests passed, including login and middleware role checks. An earlier unrestricted run had six 5-second timeouts while the Docker build was running; all passed on rerun with limited concurrency.
- `docker build --build-arg DOCKERHUB_MIRROR=docker.io/library --target nexus-console -t nexus-console:prod -f docker/Dockerfile .`: passed; image `sha256:56c9773cc52528670486e72353e0d2b64a2043f1d3222414a8732b5bf82dad45`.
- Production image `npm prune --omit=dev` audit: 0 vulnerabilities. Runtime smoke: `/login` returned 200; unauthenticated `/workbench` and `/asset-center` returned 307 to `/login`; `/api/auth/session` returned 204.
- `git diff --check`: passed.
- `npm run lint` remains blocked by undeclared `eslint-plugin-testing-library` and `eslint-plugin-vitest` imports in the existing `eslint.config.mjs`; this dependency configuration predates this task and does not enter the production image.

Frontend UX and Permission And Audit Gate assessment: no route, authentication, role, or API contract code changed; focused tests and production HTTP checks passed. Human review is required before merge under `WORKFLOWS.md`.
