---
name: Feature request
about: Propose an enhancement consistent with the architecture
labels: enhancement
---

**Problem to solve** (user story, one paragraph):

**Spec alignment**:

- Which section of LM-ARCH-001 does this touch (§ ref / FR / NFR ID)?
- Is this inside the current non-goals (§4.4)? If yes, it needs a spec change first.
- Does it add a dependency? (Requires an ADR + pinned lockfile — §17.11.)

**Proposed solution** (sketch; API/UX impact):

**Alternatives considered**:

**Privacy check**: does this introduce any path where Content leaves the
device mesh (cloud, logs, telemetry)? If yes, redesign — it contradicts CON-02.

**Willing to implement it?** yes / maybe / no
