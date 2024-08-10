# Brimdor's Homelab

**[Features](#features) • [Get Started](#get-started) • [Documentation](https://homelab.eaglepass.io)**


This project utilizes [Infrastructure as Code](https://en.wikipedia.org/wiki/Infrastructure_as_code) and [GitOps](https://www.weave.works/technologies/gitops) to automate provisioning, operating, and updating self-hosted services in my homelab.
It can be used as a highly customizable framework to build your own homelab.

> **What is a homelab?**
>
> Homelab is a laboratory at home where you can self-host, experiment with new technologies, practice for certifications, and so on.
> For more information about homelab in general, see the [r/homelab introduction](https://www.reddit.com/r/homelab/wiki/introduction).

## Overview

Project status: **BETA**

This project is still in the experimental stage, and I don't use anything critical on it.
Expect breaking changes that may require a complete redeployment.
A proper upgrade path is planned for the stable release.
More information can be found in [the roadmap](#roadmap) below.

### Hardware

- 8 × Lenovo Thinkcentre M700:
    - CPU: `Intel Core i5-6600T @ 2.70GHz`
    - RAM: `16GB`
    - SSD: `128GB`
- 1 x Lenovo Thinkcentre M900:
    - CPU: `Intel Core i7-6700 @ 4.0GHz`
    - RAM: `32GB`
    - SSD: `1TB`
- Protectli Vault FW2B:
    - CPU: `Intel Dual Core`
    - RAM: `4GB`
    - SSD: `32GB`
- Linksys `LGS124` Unmanaged Switch:
    - PORTS: `24`
    - BANDWIDTH: `10/100/1000`
- Custom NAS:
    - Operating System: `UNRAID`
    - HDD: `6 NAS Rated Drives`
    - SSD: `2 for Cache`

### Features

- [x] Common applications: Gitea, Seafile, Jellyfin, Paperless...
- [x] Automated bare metal provisioning with PXE boot
- [x] Automated Kubernetes installation and management
- [x] Installing and managing applications using GitOps
- [x] Automatic rolling upgrade for OS and Kubernetes
- [x] Automatically update apps (with approval)
- [x] Modular architecture, easy to add or remove features/components
- [x] Automated certificate management
- [x] Automatically update DNS records for exposed services
- [x] VPN without port forwarding
- [x] Expose services to the internet securely with [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/)
- [x] CI/CD platform
- [x] Private container registry
- [x] Distributed storage
- [x] Support multiple environments (dev, prod)
- [x] Monitoring and alerting
- [ ] Automated offsite backups 🚧
- [x] Single sign-on
- [x] Infrastructure testing

Some demo videos and screenshots are shown here.
They can't capture all the project's features, but they are sufficient to get a concept of it.

| Demo                                                                                                            |
| :--:                                                                                                            |
| [![][deploy-demo]](https://asciinema.org/a/xkBRkwC6e9RAzVuMDXH3nGHp7)                                           |
| Deploy with a single command (after updating the configuration files)                                           |
| [![][pxe-demo]](https://www.youtube.com/watch?v=y-d7btNNAT8)                                                    |
| PXE boot                                                                                                        |
| [![][hubble-demo]][hubble-demo]                                                                                 |
| Observe network traffic with Hubble, built on top of [Cilium](https://cilium.io) and eBPF                       |
| [![][homepage-demo]][homepage-demo]                                                                             |
| Homepage powered by... [Homepage](https://gethomepage.dev)                                                      |
| [![][grafana-demo]][grafana-demo]                                                                               |
| Monitoring dashboard powered by [Grafana](https://grafana.com)                                                  |
| [![][gitea-demo]][gitea-demo]                                                                                   |
| Git server powered by [Gitea](https://gitea.io/en-us)                                                           |
| [![][woodpecker-demo]][woodpecker-demo]                                                                         |
| Continuous integration with [Woodpecker CI](https://woodpecker-ci.org)                                          |
| [![][argocd-demo]][argocd-demo]                                                                                 |
| Continuous deployment with [ArgoCD](https://argoproj.github.io/cd)                                              |
| [![][alert-demo]][alert-demo]                                                                                   |
| [ntfy](https://ntfy.sh) displaying received alerts                                                              |
| [![][ai-demo]][ai-demo]                                                                                         |
| Self-hosted AI powered by [Ollama](https://ollama.com) (experimental, not very fast because I don't have a GPU) |

[deploy-demo]: https://asciinema.org/a/xkBRkwC6e9RAzVuMDXH3nGHp7.svg
[pxe-demo]: https://user-images.githubusercontent.com/27996771/157303477-df2e7410-8f02-4648-a86c-71e6b7e89e35.png
[homepage-demo]: https://user-images.githubusercontent.com/27996771/149445807-0f869eb7-d8f5-4fef-ab97-ac281df91a06.png
[grafana-demo]: https://user-images.githubusercontent.com/27996771/149446631-1c5d056b-1fdc-48e6-96ba-e1abe1762be0.png
[gitea-demo]: https://user-images.githubusercontent.com/27996771/149444871-38889c9d-862f-41ff-8c05-8ece21da3e9c.png
[tekton-demo]: https://user-images.githubusercontent.com/27996771/149445374-58fd0605-bb9a-46e4-81d6-5e584d2b94a9.png
[argocd-demo]: https://user-images.githubusercontent.com/27996771/149444716-fc0d7282-4cf7-4ddb-97a4-1a3fb47ff2b8.png
[lens-demo]: https://user-images.githubusercontent.com/27996771/149448896-9d79947d-468c-45c6-a81d-b43654e8ab6b.png
[vault-demo]: https://user-images.githubusercontent.com/27996771/149452309-de4a893b-e94c-4ba8-9119-ea87449cf77e.png

### Tech stack

<table>
    <tr>
        <th>Logo</th>
        <th>Name</th>
        <th>Description</th>
    </tr>
    <tr>
        <td><img width="32" src="https://simpleicons.org/icons/ansible.svg"></td>
        <td><a href="https://www.ansible.com">Ansible</a></td>
        <td>Automate bare metal provisioning and configuration</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/30269780"></td>
        <td><a href="https://argoproj.github.io/cd">ArgoCD</a></td>
        <td>GitOps tool built to deploy applications to Kubernetes</td>
    </tr>
    <tr>
        <td><img width="32" src="https://github.com/jetstack/cert-manager/raw/master/logo/logo.png"></td>
        <td><a href="https://cert-manager.io">cert-manager</a></td>
        <td>Cloud native certificate management</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/21054566?s=200&v=4"></td>
        <td><a href="https://cilium.io">Cilium</a></td>
        <td>eBPF-based Networking, Observability and Security (CNI, LB, Network Policy, etc.)</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/314135?s=200&v=4"></td>
        <td><a href="https://www.cloudflare.com">Cloudflare</a></td>
        <td>DNS and Tunnel</td>
    </tr>
    <tr>
        <td><img width="32" src="https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png"></td>
        <td><a href="https://www.docker.com">Docker</a></td>
        <td>Ephemeral PXE server and convenient tools container</td>
    </tr>
    <tr>
        <td><img width="32" src="https://github.com/kubernetes-sigs/external-dns/raw/master/docs/img/external-dns.png"></td>
        <td><a href="https://github.com/kubernetes-sigs/external-dns">ExternalDNS</a></td>
        <td>Synchronizes exposed Kubernetes Services and Ingresses with DNS providers</td>
    </tr>
    <tr>
        <td><img width="32" src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Fedora_logo.svg/267px-Fedora_logo.svg.png"></td>
        <td><a href="https://getfedora.org/en/server">Fedora Server</a></td>
        <td>Base OS for Kubernetes nodes</td>
    </tr>
    <tr>
        <td><img width="32" src="https://upload.wikimedia.org/wikipedia/commons/b/bb/Gitea_Logo.svg"></td>
        <td><a href="https://gitea.com">Gitea</a></td>
        <td>Self-hosted Git service</td>
    </tr>
    <tr>
        <td><img width="32" src="https://grafana.com/static/img/menu/grafana2.svg"></td>
        <td><a href="https://grafana.com">Grafana</a></td>
        <td>Observability platform</td>
    </tr>
    <tr>
        <td><img width="32" src="https://helm.sh/img/helm.svg"></td>
        <td><a href="https://helm.sh">Helm</a></td>
        <td>The package manager for Kubernetes</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/49319725"></td>
        <td><a href="https://k3s.io">K3s</a></td>
        <td>Lightweight distribution of Kubernetes</td>
    </tr>
    <tr>
        <td><img width="32" src="https://kanidm.com/images/logo.svg"></td>
        <td><a href="https://kanidm.com">Kanidm</a></td>
        <td>Modern and simple identity management platform</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/13629408"></td>
        <td><a href="https://kubernetes.io">Kubernetes</a></td>
        <td>Container-orchestration system, the backbone of this project</td>
    </tr>
    <tr>
        <td><img width="32" src="https://github.com/grafana/loki/blob/main/docs/sources/logo.png?raw=true"></td>
        <td><a href="https://grafana.com/oss/loki">Loki</a></td>
        <td>Log aggregation system</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/1412239?s=200&v=4"></td>
        <td><a href="https://www.nginx.com">NGINX</a></td>
        <td>Kubernetes Ingress Controller</td>
    </tr>
    <tr>
        <td><img width="32" src="https://ntfy.sh/_next/static/media/logo.077f6a13.svg"></td>
        <td><a href="https://ntfy.sh">ntfy</a></td>
        <td>Notification service to send notifications to your phone or desktop</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/3380462"></td>
        <td><a href="https://prometheus.io">Prometheus</a></td>
        <td>Systems monitoring and alerting toolkit</td>
    </tr>
    <tr>
        <td><img width="32" src="https://docs.renovatebot.com/assets/images/logo.png"></td>
        <td><a href="https://www.whitesourcesoftware.com/free-developer-tools/renovate">Renovate</a></td>
        <td>Automatically update dependencies</td>
    </tr>
    <tr>
        <td><img width="32" src="https://raw.githubusercontent.com/rook/artwork/master/logo/blue.svg"></td>
        <td><a href="https://rook.io">Rook Ceph</a></td>
        <td>Cloud-Native Storage for Kubernetes</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/48932923?s=200&v=4"></td>
        <td><a href="https://tailscale.com">Tailscale</a></td>
        <td>VPN without port forwarding</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/13991055?s=200&v=4"></td>
        <td><a href="https://www.wireguard.com">Wireguard</a></td>
        <td>Fast, modern, secure VPN tunnel</td>
    </tr>
    <tr>
        <td><img width="32" src="https://avatars.githubusercontent.com/u/84780935?s=200&v=4"></td>
        <td><a href="https://woodpecker-ci.org">Woodpecker CI</a></td>
        <td>Simple yet powerful CI/CD engine with great extensibility</td>
    </tr>
    <tr>
        <td><img width="32" src="https://zotregistry.dev/v2.0.2/assets/images/logo.svg"></td>
        <td><a href="https://zotregistry.dev">Zot Registry</a></td>
        <td>Private container registry</td>
    </tr>
</table>

## Get Started

- [Deploy on real hardware](https://homelab.eaglepass.io/installation/production/prerequisites) for production workload

## Roadmap

See [roadmap](https://homelab.eaglepass.io/reference/roadmap) and [open issues](https://github.com/brimdor/homelab/issues) for a list of proposed features and known issues.

## Contributing

Any contributions you make are greatly appreciated.

Please see [contributing guide](https://homelab.eaglepass.io/reference/contributing) for more information.

## License

Copyright &copy; 2020 - 2022 Brimdor (Edited by Brimdor) based on [khuedoan/homelab](https://github.com/khuedoan/homelab)

Distributed under the GPLv3 License.
See [license page](https://homelab.eaglepass.io/reference/license) or `LICENSE.md` file for more information.

## Acknowledgements

Based on work originating from [khuedoan/homelab](https://github.com/khuedoan/homelab) - Buy him a coffee!!
