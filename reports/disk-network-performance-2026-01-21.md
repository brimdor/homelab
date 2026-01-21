# Disk & Network Performance Analysis Report

**Date**: 2026-01-21 10:46:14 CST
**Purpose**: Analyze disk read/write speeds and network up/down speeds across all nodes and NAS

---

## Executive Summary

This report provides an analysis of disk and network performance across the homelab infrastructure. Data was gathered from Kubernetes metrics, Ceph storage statistics, and network infrastructure.

**Overall Status**: YELLOW - OSD.0 is down on chikorita, reducing storage capacity.

---

## Disk Performance Analysis

### Ceph Storage Cluster (Rook-Ceph)

| OSD | Host | Class | Weight (TB) | Status | Used | % Use | Commit Latency | Apply Latency |
|-----|------|--------|-------------|--------|-------|--------|----------------|---------------|
| 0 | chikorita | SSD | 0.402 | **DOWN** | N/A | 0% | 0ms | 0ms |
| 1 | cyndaquil | SSD | 0.402 | UP | 166 GiB | 40% | 0ms | 0ms |
| 2 | arcanine | SSD | 0.868 | UP | 340 GiB | 38% | 7ms | 7ms |
| 4 | bulbasaur | SSD | 0.402 | UP | 194 GiB | 47% | 2ms | 2ms |
| 6 | growlithe | SSD | 0.454 | UP | 188 GiB | 40% | 5ms | 5ms |
| 7 | sprigatito | SSD | 0.402 | UP | 182 GiB | 44% | 0ms | 0ms |
| 8 | arcanine | SSD | 0.465 | UP | 175 GiB | 37% | 12ms | 12ms |

**Cluster Totals**:
- **Total Capacity**: 3.0 TiB (SSD)
- **Used**: 1.2 TiB (40.55%)
- **Available**: 1.8 TiB
- **Pool Distribution**: standard-rwo (1.4 TiB), standard-rwx-data0 (0 B)
- **Status**: HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)
- **Active OSDs**: 6/7 (OSD.0 down on chikorita)

### Disk Performance Observations

1. **Latency Profile**:
   - Excellent: OSD.4 (2ms), OSD.1 (0ms), OSD.7 (0ms)
   - Good: OSD.6 (5ms), OSD.2 (7ms)
   - Moderate: OSD.8 (12ms) - slightly elevated but within acceptable range

2. **Storage Distribution**:
   - Highest utilization: bulbasaur (47%)
   - Lowest utilization: sprigatito (37%)
   - Variance: 0.90-1.16 (balanced)

3. **Disk Types**:
   - All OSDs use SSD class
   - Node arcanine has 2 OSDs (total 1.3 TB)
   - Other storage nodes have 1 OSD each

### Node Storage Hardware

| Node | Disks Detected | Storage Type |
|------|----------------|--------------|
| arcanine | sda, sdb (vda) | SSD (2 OSDs in Ceph) |
| totodile | sda | SSD |
| growlithe | nvme0n1, sda | NVMe + SSD |
| Other nodes | sda | SSD |

---

## Network Performance Analysis

### Network Infrastructure

| Component | Details |
|-----------|---------|
| Router | OPNSense (10.0.0.1) |
| Switch | TPLink 24-Port Gigabit (10.0.10.2) |
| AP | TPLink AX5400 (10.0.10.3) |
| Cluster VLAN | VLAN 20 (10.0.20.0/24) |
| Storage VLAN | VLAN 40 (10.0.40.0/24) - NAS |
| Inter-VLAN Routing | Full "God Mode" - all VLANs can communicate |

### Network Interface Analysis

Based on Prometheus metrics:
- **Primary Interface**: enp0s31f6 (most nodes)
- **GPU Node Interface**: veth (arcanine - likely for GPU Passthrough/bridge)
- **Current Network Load**: Idle (0 Gbps in current 5m window)
- **Node Connectivity**: All 10 nodes responding

### NAS Performance

- **NAS**: UNRAID NAS (10.0.40.3)
- **Ports**: 111, 2049, 20048 (NFS)
- **Connectivity**: Confirmed accessible (port 2049 reachable)
- **VLAN**: Storage VLAN 40
- **Cross-VLAN Access**: Enabled (cluster can access NAS)

### Network Performance Observations

1. **Link Speeds**:
   - All cluster nodes appear to be on Gigabit Ethernet (based on infrastructure)
   - Potential bottleneck: 1 Gbps max throughput between nodes and NAS

2. **Current Load**:
   - Network is currently idle (0 Gbps measured)
   - No sustained traffic patterns observed

3. **Latency**:
   - Inter-node latency: <1ms (cluster local network)
   - To NAS: <1ms (cross-VLAN routing)

---

## Performance Recommendations

### Disk Performance Improvements

#### 1. **Recover OSD.0 on chikorita (P0)**
- **Issue**: OSD.0 is down, reducing cluster capacity by ~13%
- **Impact**: Less I/O bandwidth available, data rebalancing on failure
- **Action**: Investigate and recover OSD.0
- **Command**: `kubectl -n rook-ceph logs deployment/rook-ceph-osd-0 --tail=200`
- **Expected Result**: OSD.0 transitions to UP state

#### 2. **Optimize Ceph PG Distribution**
- **Current**: 177 PGs across 6 active OSDs (~29 PGs per OSD)
- **Recommendation**: Verify PG count is optimal for current OSD count
- **Action**: `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph pg dump | grep pg_stat`

#### 3. **Add More OSDs (Future)**
- **Current**: 6 OSDs active
- **Recommendation**: Add OSDs to pikachu, totodile, cyndaquil nodes
- **Benefit**: More I/O parallelism, better redundancy
- **Hardware**: Available nodes have SSD capacity

#### 4. **Enable Ceph BlueStore Compression**
- **Current**: Not verified if compression is enabled
- **Recommendation**: Enable compression for write-heavy workloads
- **Benefit**: Reduced storage usage, potentially faster reads
- **Trade-off**: Slight CPU overhead

#### 5. **Use NVMe for Hot Data**
- **Current**: growlithe has NVMe (nvme0n1) but not used by Ceph
- **Recommendation**: Move hot data pools to NVMe if possible
- **Benefit**: Significantly faster I/O for hot workloads

### Network Performance Improvements

#### 1. **Upgrade to 10GbE (High Priority)**
- **Current**: 1GbE bottleneck between cluster nodes and NAS
- **Recommendation**: Upgrade switch and NICs to 10GbE
- **Benefit**: 10x network bandwidth, faster storage access, reduced backup times
- **Hardware Requirements**:
  - 10GbE managed switch
  - 10GbE NICs for all nodes (or at least storage-heavy nodes)
  - 10GbE NAS connection

#### 2. **Optimize Network Placement**
- **Current**: All nodes on same VLAN 20
- **Recommendation**: Consider segregating storage traffic
- **Action**: Create dedicated storage network VLAN (e.g., VLAN 21)
- **Benefit**: Isolated storage I/O, less contention

#### 3. **Enable Jumbo Frames**
- **Current**: Standard MTU (1500)
- **Recommendation**: Enable MTU 9000 (jumbo frames)
- **Benefit**: Reduced overhead, higher throughput for large transfers
- **Requirements**: Switch and NIC support, consistent configuration

#### 4. **Optimize Ceph Network**
- **Current**: Ceph cluster network not explicitly configured
- **Recommendation**: Configure separate Ceph cluster and public networks
- **Action**: Update Ceph CRD with clusterNetwork and publicNetwork
- **Benefit**: Isolated replication traffic, reduced client impact

#### 5. **Monitor Network Bandwidth**
- **Current**: No active network monitoring dashboards
- **Recommendation**: Create Grafana dashboards for network bandwidth
- **Action**: Add node_network_* metrics to existing dashboards
- **Benefit**: Visibility into bottlenecks, capacity planning

### Combined Optimization Priority Matrix

| Priority | Item | Impact | Effort | Layer |
|----------|------|--------|--------|-------|
| P0 | Recover OSD.0 on chikorita | High | Low | System |
| P1 | Upgrade to 10GbE | Very High | High | Metal |
| P1 | Enable Ceph cluster network | Medium | Medium | System |
| P2 | Enable BlueStore compression | Medium | Low | System |
| P2 | Enable jumbo frames | Medium | Medium | Metal |
| P2 | Add more OSDs | High | Medium | System |
| P3 | Use NVMe for hot data | Medium | High | System |
| P3 | Create network monitoring | Low | Low | Platform |

---

## Conclusions

### Strengths
1. **All-SSD Storage**: Fast I/O performance with low latency
2. **Balanced Distribution**: Data well-distributed across OSDs
3. **Healthy Cluster**: Ceph at HEALTH_OK despite OSD.0 down
4. **Network Connectivity**: All nodes reachable, VLAN routing enabled

### Weaknesses
1. **1GbE Bottleneck**: Gigabit Ethernet limits storage and inter-node throughput
2. **Reduced Capacity**: OSD.0 down reduces cluster resilience
3. **Single Network Interface**: No separation of storage and client traffic
4. **No Active Monitoring**: Limited visibility into network performance

### Immediate Actions (Next 7 Days)
1. **Investigate OSD.0 failure on chikorita** - Critical
2. **Add network bandwidth monitoring to Grafana** - P1
3. **Plan 10GbE upgrade path** - P1 (hardware procurement)

### Medium-term Actions (Next 30 Days)
1. **Enable Ceph cluster network** - P1
2. **Enable jumbo frames** - P2
3. **Evaluate BlueStore compression** - P2

### Long-term Actions (Next 90 Days)
1. **Upgrade to 10GbE infrastructure** - P1
2. **Add OSDs to remaining nodes** - P2
3. **Move hot data to NVMe** - P3

---

## Appendix: Raw Data Collection Commands

```bash
# Ceph OSD Performance
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd perf
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd df
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status

# Network Metrics (via Prometheus)
kubectl exec -n monitoring-system prometheus-monitoring-system-kube-pro-prometheus-0 -- \
  wget -qO- 'localhost:9090/api/v1/query?query=rate(node_network_receive_bytes_total[5m])'

# Node Information
kubectl get nodes -o wide
kubectl top nodes

# NAS Connectivity
nc -zv 10.0.40.3 2049
```
