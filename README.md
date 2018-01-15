vocker - Create VMs not containers
==================================

vocker can read Dockerfiles (currently just a subset), and does
build VM images from them.

Instead of using the docker registry for base images, `virt-builder`
images can be used as `FROM` sources.

vocker is building the images incerementally, for each command.
It caches the images, which makes it fast.

> Note: This is WIP. Not all features are supported (yet).

A quick demo:

[![asciicast](https://asciinema.org/a/091pvgwprx0fa5oosr4jcu9am.png)](https://asciinema.org/a/091pvgwprx0fa5oosr4jcu9am)

With more details:

[![asciicast](https://asciinema.org/a/eg1ccvapczlg6k2tql7kt4xru.png)](https://asciinema.org/a/eg1ccvapczlg6k2tql7kt4xru)


Installation
------------

```bash
$ pip install -rrequirements.txt
$ python setup.py install
```

Usage
-----

The usage should look familiar:

```bash
$ vocker build --tag simple -f examples/Dockerfile.simple
$ vocker run simple
fast_fedora
$ vocker attach fast_fedora

# Export an image
$ vocker export simple -f simple.raw
```

Hacking
-------

When in the source folder:

```bash
$ pip install -rrequirements-dev.txt
```

to install the dependencies.

```bash
$ python setup.py test
```

to run the tests.


```bash
$ python vocker.py --help
```

to run your local developer version.

Why?
----

I think it's a nice approach to have a declarative approach
for creating VMs.

Tips
----

### Setting the root password

By default a random root password is chosen. If you have to set the password
during build time you can add the build instruction

```
RUN echo "mypass" | passwd --stdin
```
