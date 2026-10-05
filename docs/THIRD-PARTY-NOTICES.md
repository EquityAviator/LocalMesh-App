# Third-Party Notices

This project is licensed under the **Apache License 2.0** (see `LICENSE` at the
repository root — decision **Q-08**, resolved by the owner on 2026-10-05 per
the M9 decision brief in `docs/RELEASE.md`).

This file records the direct third-party dependencies of each component and
their licenses, plus the extra obligations that follow from them. Exact pinned
versions live in the committed lockfiles (`agent/requirements.txt`,
`apps/mobile/bun.lock`, `bun.lock`) — never from memory (`AGENTS.md`).

## Components and direct dependencies

| Component | Direct dependencies (selected) | License |
| --- | --- | --- |
| `agent/` (Python 3.12) | fastapi, uvicorn, httpx, pydantic, pydantic-settings, cryptography, psutil, keyring | BSD-3-Clause / MIT / Apache-2.0 (permissive) |
| `agent/` — **zeroconf** (python-zeroconf) | mDNS/NSD service discovery (§16.2) | **LGPL-2.1-or-later** |
| `agent/` optional extra | nvidia-ml-py (pynvml module) | MIT |
| `apps/mobile/` (JS) | expo, expo-router, react, react-dom, react-native, react-native-web, zustand, query-string | MIT |
| `apps/mobile/modules/mesh-core` (Kotlin) | AndroidX / Kotlin stdlib (via Gradle) | Apache-2.0 |
| `packages/mesh-protocol`, dashboard (`src/`) | TypeScript, React, Next.js, Tailwind, shadcn/ui | MIT |

## zeroconf — LGPL-2.1-or-later obligations (CON-03)

The Agent uses [`python-zeroconf`](https://github.com/python-zeroconf/python-zeroconf)
for `_localmesh._tcp` mDNS advertisement/discovery. That library is licensed
under **GNU LGPL-2.1-or-later**. If you distribute a build of this project that
includes it, you must comply with the LGPL for that library, which for this
project means at minimum:

1. Include the zeroconf license text (LGPL-2.1) and copyright notices with any
   distribution of the Agent (wheel, sdist, container image, installer).
2. Keep the library dynamically linked as a normal Python import (no static
   modification of its source); if you modify zeroconf itself, release those
   modifications under the LGPL.
3. Provide the corresponding source for the exact zeroconf version you ship
   (pip makes this trivial: `pip download zeroconf==<pinned version> --no-binary :all:`).

The project's own code (Apache-2.0) remains unaffected — this is a per-component
obligation triggered only when you redistribute the Agent.

## Apache-2.0 NOTICE obligation

The Apache-2.0 grant (§4(d)) requires carrying attribution notices from this
repository's `NOTICE`-equivalent files into derivatives. Treat this file and
the `LICENSE` copyright block as that notice set.

## Reporting a license issue

If you believe a dependency license is mis-categorized or an obligation is
unmet, please open an issue referencing this file and the pinned version in
question (see `CONTRIBUTING.md`).
