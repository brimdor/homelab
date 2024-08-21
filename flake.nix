{
  description = "Homelab";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;

          overlays = [
            (final: prev: {
              kanidm = prev.kanidm.overrideAttrs (old: rec {
                version = "1.1.0-rc.16";
                src = prev.fetchFromGitHub {
                  owner = "kanidm";
                  repo = "kanidm";
                  rev = "v${version}";
                  sha256 = "NH9V5KKI9LAtJ2/WuWtUJUzkjVMfO7Q5NQkK7Ys2olU=";
                };
                cargoSha256 = "";
              });
            })
          ];
        };
        lib = pkgs.lib;
      in
      with pkgs;
      {
        devShells.default = mkShell {
          packages = [
            ansible
            ansible-lint
            bmake
            diffutils
            docker
            docker-compose_1
            dyff
            git
            go
            gotestsum
            iproute2
            jq
            k9s
            kanidm
            kube3d
            kubectl
            kubernetes-helm
            kustomize
            libisoburn
            neovim
            openssh
            p7zip
            pre-commit
            shellcheck
            terraform
            yamllint

            (python3.withPackages (p: with p; [
              jinja2
              kubernetes
              mkdocs-material
              netaddr
              pexpect
              rich
            ]))
          ];
        };
      }
    );
}
