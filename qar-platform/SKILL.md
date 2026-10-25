---
name: qar-platform
description: Use for any work on the QAR/FOQA data lakehouse capstone: ARINC 717 decoding, medallion layers, Iceberg/Trino/Dagster POC, AWS architecture, or the proposal (FR-1–FR-8).
---

# QAR Data Platform (Capstone)

Airline FOQA lakehouse built from scratch. Ingests ARINC 717 QAR files, decodes them once into a queryable multi-rate store, and computes fuel/safety/FOQA metrics as versioned definitions over that store. Serves engineering and governance use cases.

Source of truth: **QAR Data Platform Proposal** — requirements FR-1 to FR-8 plus Annex A. Anchor every answer to the proposal or to a decision listed below. If something is not from either, say so explicitly.

## Scope (first 12 months)

- Five types: A320, A330, A350, B777, B787.
- Canonical parameter dictionary, automatic flight-phase detection, query interface with parameter-level access control and audit logging.
- Out of scope: replacing existing FOQA/FDM systems, real-time/in-flight data, ending the vendor arrangement.
- Early review checkpoint once the first aircraft type is proven end-to-end.
- Proposal resources: S3 (~10 TB), an EKS cluster, software licences.

## Settled architecture — do not re-litigate unless asked

- **Medallion, three layers.**
  - Bronze: raw bytes + file registry, immutable.
  - Silver: decoded canonical parameters, quality flags, native sample rates.
  - Gold: phases, events, derived parameters, fleet aggregates.
  - Bronze+ segmentation layer was dropped — files already arrive one-per-flight.
- **Trigger:** S3 landing bucket → SQS → compute. A sweep runs alongside event triggers to catch FAP corrections and version drift.
- **Compute:** EKS (provided for the project) with Fargate. Replaced AWS Batch on Fargate (Oct 2026). The Python Silver → Gold transformer also runs on Fargate.
- **Tables:** Apache Iceberg via Glue Data Catalog; Lake Formation for column-level access.
- **Orchestrator:** Dagster (chosen over Airflow).
- **Silver → Gold:** written in Python, not SQL in the query engine.
- **Decoder:** in-house ARINC 717 decoder, validated on THA935 / HS-TQC. GRAF is a validation oracle only (esp. superframe phasing), never in the core pipeline.
- **Iceberg + Trino over DuckLake/DuckDB:** DuckLake wins on metadata growth, but Trino only reaches it via a small-community connector. Mitigate Iceberg metadata growth with limits.

## Locked principles

- File-registry row written _before_ work starts, so crashes leave evidence.
- Every Silver row stamped with decoder version + FAP version.
- Silver column names are canonical (A-5); native name, word position, and encoding kept as column metadata.
- Dictionary errors fixable as metadata changes, no full re-decode.
- Analyst role gets an explicit IAM **Deny** on the lakehouse bucket, not just a missing Allow.
- Access boundary enforced at the query engine; analysts never hold object-store credentials.
- Event definitions and phase rules are versioned artefacts.
- Rate-grouped wide schema is the lean default for Silver.

## Domain rules (ARINC 717 / FOQA)

- ARINC 717 = structural envelope (subframes, sync words). FAP/DFL = semantics (positions, bit encoding, scaling). Keep them separate.
- Superframe phase misalignment produces _silent_ errors — phasing must be validated.
- Air/ground: weight-on-wheels → radio altimeter → ground speed → airspeed, with debounce to tell landing chatter from real touch-and-go.
- Silver schema shape (FR-4) follows the query-engine decision (FR-5): enforcement approach decides whether boundaries are physical or logical.
- Known data facts (THA935): VRTG at 10 Hz, mixed sample rates, zero recording gaps.

## Open decisions — never present as settled

- **Query engine: Athena vs Trino.** Gated on whether FOQA needs cross-system joins (maintenance, scheduling, crew). POC uses Trino.
- **Missing canonical parameters on a type:** explicit unavailability marker vs handled at query layer.
- **DuckLake/FastAPI governance alternative:** fatal flaw = raw SQL forwarding lets `read_parquet` bypass governance views. Proposed fix (FastAPI builds SQL instead of forwarding) — neither accepted nor rejected.
- **Planned client library:** flight-level verbs returning Arrow, pandas default, plus a flight-summary table for performance.

## Stack

AWS (S3, SQS, EKS + Fargate, Glue, Lake Formation, Athena), Iceberg, Trino, OpenTofu, Python, PyIceberg, PyArrow, Dagster. Local dev on an M5 MacBook; notes in Obsidian.

## Current state (snapshot, Oct 2026 — check before relying on it)

- Simple POC: Iceberg + Trino + Dagster, Silver → Gold only. Learning the stack step by step — new to hands-on use.
- Preparing a demo of the POC to the project group.

## How to work with our crew here

- Terse, direct. Short fragments are fine.
- Establish base concepts before using terms that depend on them.
- When he shares an idea: find its flaws. Don't implement it or change his work unless asked.
- Surgical edits, not rewrites. Preserve code comments.
- Diagnose first; don't pile on clarifying questions.
- Design loop: propose → he pushes back → refine → lock the principle → next layer.
- He wants mechanics over recipes — show _why_ a step works, not just the step.
- Portfolio/resume write-ups: tight, two bullets.
