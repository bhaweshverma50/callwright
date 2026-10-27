# Lab PBX: Asterisk from Ubuntu's archive, configured by the files compose mounts into
# /etc/asterisk (see pjsip.conf.tmpl). Built on the VM: docker compose --profile lab build lab-pbx
FROM ubuntu:24.04
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends asterisk \
  && rm -rf /var/lib/apt/lists/*
CMD ["asterisk", "-f", "-U", "asterisk", "-G", "asterisk", "-vvv"]
