#!/usr/bin/env python3
"""Build qualification-only operand overlays; never change a production chart."""

import copy


# Keep the existing containerd-v3 toolkit patch through the first bridge.
# Later families use their exact official chart defaults for these operands.
PINS = {
    "25.3.4": ("v1.17.9-ubuntu20.04", "v0.17.4", "4.3.1-4.4.0-ubuntu22.04", "v0.12.3-ubuntu20.04"),
    "25.10.1": ("v1.18.1", "v0.18.1", "4.4.2-4.7.0-distroless", "v0.13.1"),
    "26.3.3": ("v1.19.1", "v0.19.3", "4.5.3-4.8.2-distroless", "v0.14.2"),
    "26.7.2": ("v1.20.1", "v0.20.1", "4.6.1-4.8.4-distroless", "v0.15.1"),
}


def candidate_values(source, version):
    if version not in PINS:
        raise RuntimeError("unreviewed GPU candidate family")
    if source.get("driver", {}).get("enabled") is not False:
        raise RuntimeError("candidate requires existing host-managed drivers")
    if source.get("toolkit", {}).get("version") != "v1.17.9-ubuntu20.04":
        raise RuntimeError("existing GPU toolkit prerequisite changed")
    result = copy.deepcopy(source)
    toolkit, plugin, exporter, mig = PINS[version]
    for operand, pin in (("toolkit", toolkit), ("devicePlugin", plugin), ("gfd", plugin),
                         ("dcgmExporter", exporter), ("migManager", mig)):
        result[operand]["version"] = pin
    return result
