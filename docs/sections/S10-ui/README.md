# S10 · UI (React + TypeScript)

## 1. Spec

**Goal:** a lawyer-facing workspace where every statement can be traced to its source in one click, changes are visible, and nothing is hidden.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S10-1 | Matter list/create; upload a batch (multi-file, drag-drop), see per-file progress, failures and duplicates, commit |
| S10-2 | Views: **Gist** (current position), **Chronology** (superseded struck through), **Claims** (by party, with evidence), **Directions** (computed due dates, overdue), **What changed** per batch, **Ask**, **Legal research**, **Hearing brief**, **Review queue**, **Documents** |
| S10-3 | Every sentence has citations; clicking one opens the PDF at the page with the quote **highlighted** |
| S10-4 | **As-of batch** selector re-renders any view as it stood after batch N |
| S10-5 | State badges (CURRENT, SUPERSEDED, DISPUTED), UNVERIFIED badge on legal authorities, notes when an answer used the model-free fallback |
| S10-6 | Loading, empty and error states for every view; errors show the server's message and request id |
| S10-7 | Labelled controls and a login screen when auth is enabled; laptop-width layout (no formal accessibility audit) |

## 2. Plan

Vite + React 18 + TS (strict) → typed API client (`api.ts`) with error mapping → hooks → shared components (`Sentences`, `Viewer`) → one file per view → unit/component tests (vitest + Testing Library) → Playwright browser flow.

## 3. Execution report

**Built:** `ui/src/{api,types,format,hooks,App,main}.ts(x)`, `components/{common,Sentences,Viewer,Login,NewMatter}.tsx`, `views/*.tsx`, served by the API from `ui/dist` (single process) or by nginx (`ui/Dockerfile`).

**Verified (real runs):**

- `npm run lint` clean, `npm run typecheck` clean, `npm run build` succeeds.
- `npm test` → **44 passed** (6 files: API client incl. error/problem+json/401 handling, formatters, sentence/citation rendering, viewer, forms, views incl. empty/error/loading states).
- **Browser E2E** (`node ui/e2e/flow.cjs`, Playwright + Chromium, against the real API and database in fixture mode): create matter → upload batch 1 → commit → open source with highlight →
  upload batch 2 → What-changed → as-of batch 1 → directions → ask "what is unpaid" → legal research → hearing brief → review queue. It passes and writes the 14 screenshots in `docs/screenshots/`.

**Not verified:** cross-browser (only Chromium), mobile layouts, screen-reader testing, UI against a real LLM.
