"""Agent CLI: `run | doctor | pair | devices | revoke` (LM-ARCH-001 §10.1).

M0 scaffold: the subcommands are delivered with their milestones (§22.1) —
`run` (M1), `pair`/`devices`/`revoke` (M2), `doctor` (M3). This stub
implements no flags or options beyond reporting scaffold status so that no
contract surface is invented ahead of its milestone (§1.2 anti-hallucination).
"""


def main() -> int:
    print(
        "localmesh-agent: M0 scaffold. CLI subcommands arrive with M1+ per "
        "LM-ARCH-001 §22.1 (run M1; pair/devices/revoke M2; doctor M3)."
    )
    return 0
