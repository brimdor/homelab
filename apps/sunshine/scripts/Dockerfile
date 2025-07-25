ARG SUNSHINE_VERSION=latest
ARG SUNSHINE_OS=archlinux
FROM lizardbyte/sunshine:${SUNSHINE_VERSION}-${SUNSHINE_OS}

USER root

# Install wayland-utils, python, and python-pip for Arch Linux
RUN pacman -Syu --noconfirm \
    wayland-utils \
    weston \
    python \
    python-pip && \
    pacman -Scc --noconfirm

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 47990

ENTRYPOINT ["/entrypoint.sh"]
