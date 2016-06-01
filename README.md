vocker - Create VMs not containers
==================================

vocker can read Dockerfiles (currently just a subset), and does
build VM images from them.

Instead of using the docker registry for base images, `virt-builder`
images can be used as `FROM` sources.


> Note: This is WIP


Usage
-----

The usage should look familiar:

    $ ./vocker build --tag simple < examples/Dockerfile.simple
    $ ./vocker run simple
    fast_fedora
    $ ./vocker attach fast_fedora
