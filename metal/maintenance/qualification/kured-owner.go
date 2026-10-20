// Exercise the exact upstream Kured lock against a loopback-only fixture API.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"time"

	"github.com/kubereboot/kured/pkg/daemonsetlock"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

func main() {
	if len(os.Args) != 4 {
		panic("expected loopback API, operation and synthetic owner")
	}
	u, err := url.Parse(os.Args[1])
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.Path != "" {
		panic("only the owned loopback fixture API is allowed")
	}
	client, err := kubernetes.NewForConfig(&rest.Config{Host: u.String(), Timeout: 15 * time.Second,
		ContentConfig: rest.ContentConfig{ContentType: "application/json", AcceptContentTypes: "application/json"}})
	if err != nil {
		panic(err)
	}
	if _, err := client.AppsV1().DaemonSets("kured").Get(context.Background(), "kured", metav1.GetOptions{}); err != nil {
		panic("fixture API preflight failed: " + err.Error())
	}
	lock := daemonsetlock.New(client, os.Args[3], "kured", "kured", "weave.works/kured-node-lock", 0, 1, 0)
	result := map[string]interface{}{}
	switch os.Args[2] {
	case "acquire":
		ok, holder, err := lock.Acquire(daemonsetlock.NodeMeta{Unschedulable: false})
		result["acquired"], result["holder"] = ok, holder
		if err != nil {
			result["error"] = err.Error()
		}
	case "release":
		if err := lock.Release(); err != nil {
			result["error"] = err.Error()
		} else {
			result["released"] = true
		}
	default:
		panic("unsupported fixture operation")
	}
	data, err := json.Marshal(result)
	if err != nil {
		panic(err)
	}
	fmt.Println(string(data))
}
