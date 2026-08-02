---
name: medblocks
description: Use when building with Medblocks. Covers Patient Access connection flows (hosted auth, own UI, patient sessions, return handling, connection status), FHIR records out (SDK records, /records REST fallback, pagination, Patient identifier mapping, FHIR server destinations), and integration best practices (SDK vs REST, API keys, webhook signatures, empty records, integration drift).
---

# Medblocks

Medblocks gives applications access to a patient's longitudinal health data, with their consent, across EHRs, payer APIs, and health information networks, through a single API.

This folder contains task guides alongside this file. Read the guide that matches the task before writing code:

| Task | Read |
| --- | --- |
| Patient Access: hosted auth, own UI connection flows, patient sessions, return handling, connection status | `patient-access.md` |
| FHIR records out: read, sync, store, or export records, pagination, Patient identifier mapping, FHIR server destinations | `export-fhir.md` |

The rest of this file is the stable integration playbook that applies to every Medblocks task. Medblocks docs and product behavior move quickly, so verify exact request fields, filters, response fields, and examples against the latest docs and generated API reference before writing code.

- Docs: https://medblocks.com/docs
- API reference: https://medblocks.com/docs/reference/api
- API conventions: https://medblocks.com/docs/reference/conventions
- Local spec for this repo, when present: `openapi/medblocks.json`

## Source Of Truth

- Keep this skill limited to stable method names, security rules, pagination shape, webhook verification, and cross-page semantics.
- Do not copy large API tables or full payload schemas into generated code from memory.
- When docs, SDK, API, or prompt behavior changed recently, inspect the current docs and API reference first.

## SDK First

For TypeScript and JavaScript apps, prefer the SDK.

```bash
npm install medblocks
```

```ts
import { Medblocks } from "medblocks";

const apiKey = process.env.MEDBLOCKS_API_KEY;
if (!apiKey) throw new Error("MEDBLOCKS_API_KEY is required");

export const mb = new Medblocks(apiKey);
```

Use REST only when the app is not TS/JS, the SDK does not expose the needed operation, the user explicitly asks for raw HTTP, or the app already has a deliberate REST client layer.

Core primitives to recognize:

| Need | Stable primitive |
| --- | --- |
| Start patient authorization | `mb.patientSession.init(input)` |
| Verify a returned session | `mb.patientSession.retrieve(id)` |
| Read patient connections | `mb.patients.getConnections(id, params?)` |
| Read FHIR records | `mb.patients.records(id, params?)` |
| Verify webhook signature | `Medblocks.webhooks.constructEvent(rawBody, signature, secret)` |
| Parse Patient Access return URL | `parseReturnUrl(searchParams?)` |

If a task needs more than this, check the docs/API reference for the exact current surface.

## Secrets And PHI

- Keep `MEDBLOCKS_API_KEY` server-side only.
- Never expose API keys through public env vars, browser bundles, URLs, client logs, or screenshots.
- Browser code should call the app backend. The backend calls Medblocks.
- Do not log API keys, webhook secrets, bearer tokens, access tokens, or full FHIR resources.
- Prefer request IDs, event IDs, patient IDs, source IDs, status codes, and counts for support logs.

## Pagination

Paginated responses use `data`, `has_more`, and `next_cursor`. Pass `next_cursor` back as `starting_after`. Cursors are opaque.

```ts
let starting_after: string | undefined;

while (true) {
  const page = await mb.patients.records(patientId, {
    count: 100,
    starting_after,
  });

  // Process page.data.

  if (!page.has_more || !page.next_cursor) break;
  starting_after = page.next_cursor;
}
```

## Webhooks

Use webhooks for asynchronous work such as background record availability. Always verify signatures with the SDK before trusting the event.

```ts
const event = await Medblocks.webhooks.constructEvent(
  rawBody,
  signature,
  process.env.MEDBLOCKS_WEBHOOK_SECRET!,
);
```

For current event names and webhook management calls, check the docs/API reference before implementation.

## Drift Boundary

Update this skill only when a stable primitive, security rule, pagination convention, webhook verification path, or promoted integration path changes.

Do not update this skill for ordinary docs wording, newly added optional parameters, expanded examples, or page-specific copy. Those belong in the docs.
