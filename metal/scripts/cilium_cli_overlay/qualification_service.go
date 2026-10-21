// SPDX-License-Identifier: Apache-2.0
// Homelab qualification overlay for cilium-cli v0.20.1; no production agent changes.
package tests

import (
	"fmt"
	"net"

	corev1 "k8s.io/api/core/v1"

	"github.com/cilium/cilium/cilium-cli/connectivity/check"
	"github.com/cilium/cilium/cilium-cli/utils/features"
)

func qualificationServiceFlowParameters(svc check.Service, family features.IPFamily, pods map[string]check.Pod, podSocketLB bool) (check.FlowParameters, error) {
	invalid := func() (check.FlowParameters, error) {
		return check.FlowParameters{}, fmt.Errorf("qualification requires one live Service and one ready selector-matched echo backend")
	}
	if svc.Service == nil || svc.Service.UID == "" || svc.Service.DeletionTimestamp != nil ||
		svc.Service.Name == "" || svc.Service.Namespace == "" || len(svc.Service.Spec.Selector) == 0 || len(svc.Service.Spec.Ports) != 1 ||
		len(svc.Service.Spec.ClusterIPs) != 1 || len(svc.Service.Spec.IPFamilies) != 1 ||
		svc.Service.Spec.ClusterIP != svc.Service.Spec.ClusterIPs[0] ||
		(family != features.IPFamilyV4 && family != features.IPFamilyV6) {
		return invalid()
	}
	validIP := func(address string) bool {
		ip := net.ParseIP(address)
		return ip != nil && !ip.IsUnspecified() && !ip.IsLoopback() &&
			((family == features.IPFamilyV4) == (ip.To4() != nil))
	}
	if !validIP(svc.Address(family)) || svc.Port() == 0 || svc.Port() > 65535 {
		return invalid()
	}
	var backend check.Pod
	matches := 0
	for _, pod := range pods {
		if pod.Pod != nil && pod.Namespace() == svc.Service.Namespace && hasAllLabels(pod, svc.Service.Spec.Selector) {
			backend = pod
			matches++
		}
	}
	if matches != 1 || backend.Pod.Name == "" || backend.Pod.UID == "" || backend.Pod.DeletionTimestamp != nil ||
		backend.Pod.Status.Phase != corev1.PodRunning || !validIP(backend.Address(family)) ||
		backend.Port() != svc.Port() {
		return invalid()
	}
	ready := 0
	for _, condition := range backend.Pod.Status.Conditions {
		if condition.Type == corev1.PodReady {
			if condition.Status != corev1.ConditionTrue {
				return invalid()
			}
			ready++
		}
	}
	if ready != 1 {
		return invalid()
	}
	// Literal ClusterIP requests do not perform DNS. Keep the Service IP match;
	// socket LB may translate it to this exact known backend before TCP tracing.
	params := check.FlowParameters{DNSRequired: false, AltDstPort: svc.Port()}
	if podSocketLB {
		params.AltDstIP = backend.Address(family)
	}
	return params, nil
}
