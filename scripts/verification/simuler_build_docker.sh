#!/bin/bash
# Simulation de VRAIS `docker build` quand Docker Hub / les depots Debian sont injoignables (environnement restreint).
# Principe : un demon dockerd local (vfs) + des images de base locales qui remplacent python:3.12-slim et node:22-alpine
# (rootfs Ubuntu 24.04 via debootstrap + Python 3.12 / Node 22). Les Dockerfile sont construits TELS QUELS.
# Ecarts avec la production : Ubuntu noble au lieu de Debian trixie (memes noms de paquets pour ceux utilises ici),
# glibc au lieu de musl pour le frontend. Pre-requis : root, dockerd, debootstrap, proxy HTTPS (HTTPS_PROXY) + CA.
# Lancer depuis la racine du depot ; voir ROADMAP.md (« Build Docker simule »).
set -e
P="${HTTPS_PROXY:?HTTPS_PROXY requis}"
BA="--network host --build-arg HTTP_PROXY=$P --build-arg HTTPS_PROXY=$P --build-arg http_proxy=$P --build-arg https_proxy=$P"
docker build $BA -t workflows-api:sim .
docker build $BA -t workflows-web:sim ./frontend
# Controles : utilisateur non root, polices, PDF, Pillow/WeasyPrint dans l'image
docker run --rm workflows-api:sim sh -c 'id -u; fc-list | wc -l; python -c "import PIL, weasyprint; from weasyprint import HTML; print(len(HTML(string=\"<p>é €</p>\").write_pdf()))"'
