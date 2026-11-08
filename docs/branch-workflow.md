# Branch ownership and collaboration

The project brief in [docs/project-brief.md](project-brief.md) defines the scope and team responsibilities. Each person starts on the branch below and opens a pull request (PR) to `main` when a small, working change is ready.

| Owner | Starting branch | First area of work |
|---|---|---|
| Abdul Kareem — Backend Lead | `feature/api-incidents` | FastAPI app structure, Firebase Auth/Firestore integration, incident API and shared event contract |
| Hania — Backend and Computer Vision Engineer | `feature/person-zone-worker` | Video input, person detection/tracking, restricted-zone rule and structured events |
| Minal — Frontend Lead and UI Systems | `feature/monitoring-ui` | Next.js foundation, theme and responsive UI system, monitoring/camera screen |
| Musaykah — Frontend Engineer and Incident Workflows | `feature/incident-review-ui` | Incident list, filters, detail/evidence view and acknowledgement flow |

## Daily workflow

1. Fetch the latest `main` and work on your own branch. Do not commit secrets, footage or model weights.
2. Keep changes focused. Agree on API/event fields in `contracts/` with Abdul Kareem before integrating frontend or the vision worker.
3. Open a PR into `main`; describe the change, how it was checked, and screenshots for UI changes. Request at least one teammate's review.
4. Address review feedback and merge only after checks pass. Pull the latest `main` before starting the next task.
5. Use a new short-lived `feature/<task-name>` branch for each later task; the four branches above identify the initial owners, not permanent personal development branches.

Repository administrators should enable a `main` branch ruleset requiring a pull request and at least one approval, and should disable bypass for collaborators. A branch name alone does not prevent direct pushes.
