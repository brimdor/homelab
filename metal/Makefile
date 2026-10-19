.POSIX:

env ?= prod
limit ?=
export KUBECONFIG = $(shell pwd)/kubeconfig.yaml

ifneq ($(limit),)
  limit_arg = --limit $(limit)
endif

default: boot cluster nodes

~/.ssh/id_ed25519:
	ssh-keygen -t ed25519 -P '' -f "$@"

boot: ~/.ssh/id_ed25519
	ansible-playbook \
		--inventory inventories/${env}.yml \
		--tags pxe \
		boot.yml
	ansible-playbook \
		--inventory inventories/${env}.yml \
		$(limit_arg) \
		--skip-tags pxe \
		boot.yml

cluster:
	ansible-playbook \
		--inventory inventories/${env}.yml \
		$(limit_arg) \
		cluster.yml

nodes:
	ansible-playbook \
		--inventory inventories/${env}.yml \
		$(limit_arg) \
		nodes.yml

console:
	ansible-console \
		--inventory inventories/${env}.yml \
		$(limit_arg)

.PHONY: ssh-trust ssh-trust-refresh kubevip-standby

# One explicitly selected nonleader only; never invokes provisioning or k3s roles.
kubevip-standby:
	@test -n "$(limit)"
	ansible-playbook --inventory inventories/${env}.yml --limit "$(limit)" kubevip-standby.yml $(kubevip_args)

ssh-trust:
	python3 scripts/ssh-trust.py

ssh-trust-refresh:
	ansible-playbook --inventory localhost, --connection local ssh-trust.yml
