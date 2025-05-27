# perccli-status

Nagios/Opsview plugin to check status of PowerEdge RAID Controller, mimics
`megaclisas-status` and `megaclisas-status --nagios`.


## Tested with

* Debian 12 Bookworm, PERC H965i, perccli2 8.4.0.22
* Debian 13 Trixie, PERC H740P, perccli64 7.2313


## Install

```
git clone
```


## Development

```
git clone git@github.com:bodik/perccli-status.git /opt/perccli-status
cd /opt/perccli-status
make install-dev
. venv/bin/activate
make coverage
make lint

make build-deb
```
