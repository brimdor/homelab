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
		$(limit_arg) \
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
