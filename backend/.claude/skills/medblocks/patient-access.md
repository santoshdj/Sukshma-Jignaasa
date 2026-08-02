# Medblocks Patient Access

Use this guide to plan and implement Patient Access integrations. Keep implementation grounded in the latest docs because product flows and examples may change.

- Patient Access docs: https://medblocks.com/docs/patient-access
- API reference: https://medblocks.com/docs/reference/api
- Local spec for this repo, when present: `openapi/medblocks.json`

## Phase 1: Planning

### Scan

Inspect the app before proposing code:

- Framework and backend boundary.
- Environment variable pattern.
- Patient identity model and stable patient id.
- Existing API client or SDK usage.
- Routes/pages for start, return, and post-connection states.
- Tests and local smoke-test conventions.

### Ask

Ask only what the scan cannot answer:

1. Should the app use the hosted Patient Access page or build its own source selection UI?
2. What stable app patient id should Medblocks receive as `patient_id`?
3. Where should the patient return after authorization?
4. What should happen after connection: show status, read records, export records, or wait for a webhook?
5. Are there source, payer, EHR, or environment constraints that the docs do not reveal?

### Confirm

Summarize the implementation plan and wait for confirmation unless the user explicitly asked for one-shot implementation.

## Phase 2: Implementation

For TypeScript and JavaScript apps, prefer the SDK.

```bash
npm install medblocks
```

```ts
import { Medblocks, parseReturnUrl } from "medblocks";

const apiKey = process.env.MEDBLOCKS_API_KEY;
if (!apiKey) throw new Error("MEDBLOCKS_API_KEY is required");

const mb = new Medblocks(apiKey);
```

Core implementation steps:

1. Create or reuse the app patient.
2. Start a patient session with `mb.patientSession.init`.
3. Redirect the patient to the returned authorization URL.
4. On return, parse the query with `parseReturnUrl`.
5. Verify the session server-side with `mb.patientSession.retrieve`.
6. Inspect connection state with `mb.patients.getConnections`.
7. Read records with `mb.patients.records` only when the product flow needs app-controlled reads.

## Hosted Page Flow

Use the hosted page when Medblocks should handle source discovery and authorization UI. The app supplies the patient id and return URL, then redirects to the session URL returned by Medblocks.

Check current docs/API reference for the exact `patientSession.init` input and response shape before coding.

## Own UI Flow

Use your own UI when the product needs custom source selection. Search or display sources with the current SDK/API catalog surface, then start the patient session with the selected source or connection as documented.

Do not hard-code source IDs unless the product explicitly requires a fixed source.

## Return Handling

The return page is a handoff, not the source of truth.

- Parse the return query.
- Retrieve the patient session server-side.
- Show a clear success, pending, canceled, or error state.
- Do not treat a completed browser session as proof that records are already available.

## Connection Status

Use `mb.patients.getConnections` to inspect patient connections. Treat `connections[].status === "active"` as the connected signal unless the current docs define a newer rule.

Records may arrive after the connection becomes active. For production record workflows, prefer a webhook or export destination over assuming records are ready immediately on the return page.

## Records After Connection

Use `mb.patients.records(patientId, params?)` for TS/JS app-controlled reads. Preserve pagination with `has_more`, `next_cursor`, and `starting_after`.

For FHIR storage, transformation, export, and identifier mapping, read `export-fhir.md` in this folder.

## Security Checklist

- Keep the Medblocks API key server-side.
- Never put bearer tokens or API keys in browser code.
- Store only the patient/session/connection identifiers the app needs.
- Avoid logging full FHIR resources or authorization payloads.
- Verify webhook signatures before processing async events.

## Drift Boundary

Update this guide when Patient Access stable semantics change: session start, return verification, connected status, record-read timing, or the recommended hosted vs own-UI flow.

Do not update this guide for every new optional parameter, screenshot, or page copy change. Link to the live docs for those.
