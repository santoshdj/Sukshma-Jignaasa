# Export FHIR From Medblocks

Use this guide when an app needs to read, sync, store, or forward FHIR records from Medblocks. For TS/JS apps, lead with the SDK records function and verify exact filters/fields against the latest docs and API reference.

- Data out: https://medblocks.com/docs/data-out
- Export to FHIR server: https://medblocks.com/docs/export-to-fhir-server
- API reference: https://medblocks.com/docs/reference/api
- Local spec for this repo, when present: `openapi/medblocks.json`

## Phase 1: Planning

### Scan

Inspect the app before proposing code:

- Existing Medblocks SDK/API usage.
- Backend boundary, job runner, queue, webhook receiver, or cron.
- Patient identity model and stable app patient id.
- Existing FHIR storage, raw JSON storage, or derived clinical models.
- Destination: app database, file export, internal FHIR server, custom FHIR server, or downstream API.
- Tests, fixtures, retries, and idempotency patterns.

### Ask

Ask only what the scan cannot answer:

1. Which destination should receive records?
2. Which patients should be included?
3. Which FHIR resource types are needed?
4. Should the app preserve raw FHIR, derive app models, or do both?
5. What should trigger sync: webhook, schedule, manual action, return flow, or existing job?
6. What retry, replay, and failure behavior is expected?
7. Does the destination require FHIR R4 resources, NDJSON, bundles, or another shape?

### Confirm

Summarize the plan, including patient scope, destination, filters, pagination, retries, and identifier mapping. Wait for confirmation unless the user explicitly asked for one-shot implementation.

## Phase 2: Implementation

For TypeScript and JavaScript apps, use the SDK records function as the primary path.

```ts
import { Medblocks } from "medblocks";

const apiKey = process.env.MEDBLOCKS_API_KEY;
if (!apiKey) throw new Error("MEDBLOCKS_API_KEY is required");

const mb = new Medblocks(apiKey);

const page = await mb.patients.records(patientId, {
  count: 100,
});
```

Use `/records` REST only for non-TS/JS apps, SDK gaps, explicit raw HTTP work, or a deliberate existing REST client layer.

## Pagination

Use `has_more`, `next_cursor`, and `starting_after`. Cursors are opaque and must be passed back exactly.

```ts
let starting_after: string | undefined;

while (true) {
  const page = await mb.patients.records(patientId, {
    count: 100,
    starting_after,
  });

  for (const item of page.data) {
    // Write or forward item.resource.
  }

  if (!page.has_more || !page.next_cursor) break;
  starting_after = page.next_cursor;
}
```

Keep filters stable across every page in the same read.

## FHIR Representation Rules

- Preserve raw FHIR resources unless the app clearly needs only derived data.
- If deriving app models, keep the raw resource or a pointer for audit, replay, and future fields.
- Upsert idempotently by app patient id, source id when present, FHIR resource type, FHIR resource id, and version/timestamp when the destination needs versions.

## Critical Patient Identifier Rule

The app's patient identifier should be read from the FHIR `Patient` resource `identifier` array. Medblocks adds it with:

```json
{
  "system": "urn:medblocks:patient-id",
  "value": "user_42"
}
```

Do not expect every FHIR resource to contain the app patient identifier.

For non-Patient resources, associate records through FHIR references such as `subject`, `patient`, or `encounter`, through the record envelope returned by Medblocks when present, or through the known patient scope of the export job.

## FHIR Server Destinations

Use an internal FHIR server or custom FHIR server destination when Medblocks should keep a FHIR endpoint updated for the workspace or downstream system.

Use SDK records when the app needs app-owned storage, custom transformation, immediate on-demand reads, or custom export jobs.

## Retries And Triggers

- Prefer an async trigger such as a record-sync webhook or existing job runner for production sync.
- Write pages idempotently.
- Advance checkpoints only after successful writes.
- Keep a manual replay path for failed patients, destinations, or pages.
- Do not log full FHIR resources unless the app already has a PHI-safe logging policy.

## Troubleshooting

- Empty records after connection: a connection can be active before records are available.
- Missing app patient id on Observations or Conditions: read it from the Patient resource and link other resources through references or job context.
- Duplicate records: fix the idempotency key, not the pagination loop.
- Skipped or repeated pages: treat `next_cursor` as opaque and preserve filters.

## Drift Boundary

Update this guide when the records SDK method, `/records` fallback, pagination shape, Patient identifier rule, or recommended export path changes.

Do not update this guide for ordinary docs copy, new screenshots, optional filters, or expanded examples. Those belong in the docs/API reference.
