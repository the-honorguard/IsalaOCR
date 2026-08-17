# IsalaOCR 3.11.12

Table Cell Reviewer action placement cleanup.

- Moved `+ Ontbrekende cel` out of the generic canvas tools.
- The action now sits directly with the review decisions (`Includeren`, `Incorrect`, `Kader aanpassen`) in the persistent review dock.
- The action still enters direct draw mode immediately; no modal or extra confirmation was reintroduced.
- In fullscreen review the missing-cell action therefore remains available even while the extended Tools panel is collapsed.
