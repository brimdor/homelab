# Network Upgrade Documentation

This section contains the documentation for the VLAN network upgrade migration from a flat network to a segmented VLAN architecture.

## Overview

The network upgrade involved:
- Migrating from a Linksys unmanaged switch to a TPLink managed switch
- Implementing VLANs for network segmentation
- Configuring OPNSense for inter-VLAN routing
- Setting up LAG (Link Aggregation) for redundancy

## Migration Phases

| Phase | Description | Duration | Risk |
|-------|-------------|----------|------|
| [Phase 0](phase-0-pre-migration.md) | Pre-Migration Preparation | 30-60 min | None |
| [Phase 1](phase-1-switch-configuration.md) | TPLink Switch Configuration | 45-90 min | None |
| [Phase 2](phase-2-opnsense-vlan.md) | OPNSense VLAN Configuration | 60-90 min | Low |
| [Phase 3](phase-3-firewall-rules.md) | Firewall Rules Configuration | 15 min | Low |
| [Phase 4](phase-4-physical-migration.md) | Physical Migration | 2-4 hours | Moderate |
| [Phase 5](phase-5-qos-optimization.md) | QoS and Traffic Optimization | 30-45 min | None |
| [Phase 6](phase-6-verification.md) | Verification and Testing | 30-60 min | None |
| [Phase 7](phase-7-documentation.md) | Documentation and Cleanup | 30 min | None |

## Additional Documentation

- [NAS 2-Port Configuration](update-nas-2-port.md) - Updating switch for NAS LAG configuration

## Key Considerations

!!! warning "Critical: NAS Connectivity"
    The NAS runs Twingate connectors. If NAS loses network connectivity during migration, remote access will be severed. Always ensure NAS connectivity before making changes.

!!! info "Rollback Procedure"
    If migration fails at any point:
    1. Move affected device back to original switch
    2. Restore OPNSense backup from Phase 0
    3. Factory reset TPLink switch if necessary
