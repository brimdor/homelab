// SPDX-License-Identifier: Apache-2.0
package tests

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	"github.com/cilium/cilium/cilium-cli/connectivity/check"
	"github.com/cilium/cilium/cilium-cli/utils/features"
)

func qualificationServiceFixture() (check.Service, map[string]check.Pod) {
	svc := check.Service{Service: &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{Name: "echo", Namespace: "qualification", UID: "service-uid"},
		Spec: corev1.ServiceSpec{Selector: map[string]string{"echo": "selected"},
			ClusterIP: "10.43.0.10", ClusterIPs: []string{"10.43.0.10"}, IPFamilies: []corev1.IPFamily{corev1.IPv4Protocol},
			Ports: []corev1.ServicePort{{Port: 8080, TargetPort: intstr.FromInt32(8080)}}},
	}}
	pod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "echo-pod", Namespace: "qualification", UID: "pod-uid", Labels: map[string]string{"echo": "selected"}},
		Status: corev1.PodStatus{Phase: corev1.PodRunning, PodIPs: []corev1.PodIP{{IP: "10.0.2.10"}},
			Conditions: []corev1.PodCondition{{Type: corev1.PodReady, Status: corev1.ConditionTrue}}}}
	return svc, map[string]check.Pod{"selected": check.NewPod(nil, pod, "http", "/", 8080)}
}

func TestQualificationServiceExactBackend(t *testing.T) {
	for _, socketLB := range []bool{false, true} {
		svc, pods := qualificationServiceFixture()
		other := pods["selected"].Pod.DeepCopy()
		other.Labels["echo"] = "unrelated"
		other.Status.PodIPs[0].IP = "10.0.2.99"
		pods["unrelated"] = check.NewPod(nil, other, "http", "/", 8080)
		params, err := qualificationServiceFlowParameters(svc, features.IPFamilyV4, pods, socketLB)
		if err != nil || params.DNSRequired || params.AltDstPort != 8080 {
			t.Fatalf("literal-Service parameters invalid: %+v %v", params, err)
		}
		want := ""
		if socketLB {
			want = "10.0.2.10"
		}
		if params.AltDstIP != want {
			t.Fatalf("alternate backend %q, want exact %q", params.AltDstIP, want)
		}
	}
}

func TestQualificationServiceRefusals(t *testing.T) {
	for _, change := range []string{"nil-service", "service-uid", "service-deleting", "selector", "ports", "port-zero", "service-ip", "cluster-ips", "ip-families", "missing", "ambiguous", "namespace", "labels", "pod-uid", "pod-deleting", "pod-phase", "pod-ip", "pod-ip-family", "pod-port", "ready-missing", "ready-false", "ready-duplicate", "any-family"} {
		t.Run(change, func(t *testing.T) {
			svc, pods := qualificationServiceFixture()
			pod := pods["selected"].Pod
			family := features.IPFamilyV4
			now := metav1.Now()
			switch change {
			case "nil-service":
				svc.Service = nil
			case "service-uid":
				svc.Service.UID = ""
			case "service-deleting":
				svc.Service.DeletionTimestamp = &now
			case "selector":
				svc.Service.Spec.Selector = nil
			case "ports":
				svc.Service.Spec.Ports = nil
			case "port-zero":
				svc.Service.Spec.Ports[0].Port = 0
			case "service-ip":
				svc.Service.Spec.ClusterIPs[0] = "not-an-address"
			case "cluster-ips":
				svc.Service.Spec.ClusterIPs = nil
			case "ip-families":
				svc.Service.Spec.IPFamilies = nil
			case "missing":
				delete(pods, "selected")
			case "ambiguous":
				pods["second"] = check.NewPod(nil, pod.DeepCopy(), "http", "/", 8080)
			case "namespace":
				pod.Namespace = "another"
			case "labels":
				pod.Labels["echo"] = "unrelated"
			case "pod-uid":
				pod.UID = ""
			case "pod-deleting":
				pod.DeletionTimestamp = &now
			case "pod-phase":
				pod.Status.Phase = corev1.PodPending
			case "pod-ip":
				pod.Status.PodIPs[0].IP = "not-an-address"
			case "pod-ip-family":
				pod.Status.PodIPs[0].IP = "fd00::10"
			case "pod-port":
				pods["selected"] = check.NewPod(nil, pod, "http", "/", 9999)
			case "ready-missing":
				pod.Status.Conditions = nil
			case "ready-false":
				pod.Status.Conditions[0].Status = corev1.ConditionFalse
			case "ready-duplicate":
				pod.Status.Conditions = append(pod.Status.Conditions, pod.Status.Conditions[0])
			case "any-family":
				family = features.IPFamilyAny
			}
			if _, err := qualificationServiceFlowParameters(svc, family, pods, true); err == nil {
				t.Fatal("invalid identity/backend was accepted")
			}
		})
	}
}
