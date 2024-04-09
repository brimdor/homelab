#!/bin/sh

VALUES="values.yaml"

kubectl get ingress argocd-server --namespace argocd ||
    VALUES="values-seed.yaml"

kubectl get pods --namespace argocd
kubectl get services --namespace argocd
