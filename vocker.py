#!/usr/bin/env python3

import sys
import sh
import os
import hashlib
import logging
import argparse
import random
import tempfile
import ipaddress
import errno
import xml.etree.ElementTree as ET


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger()


BASE = os.path.expanduser("~/.cache/vocker/")
IMAGES_DIR = BASE + "images/"


builder = sh.virt_builder.bake()
qemu_img = sh.qemu_img.bake()
fish = sh.guestfish.bake("--network", "-ia")
virt_install = sh.virt_install


def namegen():
    attr = ["fancy", "strong", "crazy", "atomic", "friendly", "thoughtful", "mindful", "bar", "peaceful"]
    nom = ["star", "tree", "grass", "einstein", "unicorn", "foo", "planet", "stone", "grape", "fedora"]

    random.shuffle(attr)
    random.shuffle(nom)

    return "%s_%s" % (attr.pop(), nom.pop())


def subnetgen():
    # TODO come up with something real
    return "10.%d.%d.0/24" % (random.randint(0, 255), random.randint(0, 255))


def md5sum(txt):
    m = hashlib.md5()
    m.update(txt.encode("utf-8"))
    return str(m.hexdigest())


class Layer():
    parent = None
    name = None

    @property
    def filename(self):
        return IMAGES_DIR + self.name

    def __str__(self):
        return "<Layer %s />" % self.name

    def derived_name(self, op):
        return str(md5sum("%s+%s" % (self.name, op)))

    def derive_for_op(self, op):
        return self.derive(self.derived_name(op))

    def derive(self, name):
        layer = Layer()
        layer.parent = self
        layer.name = name

        log.debug("Deriving layer %s from %s" % (layer,
                                                 layer.parent))

        return layer

    def create(self):
        log.debug("Creating layer %s from %s" % (self,
                                                 self.parent))

        qemu_img.create("-fqcow2", "-o", "backing_file=%s" % self.parent.filename, self.filename)

    def export(self, dstfn):
        qemu_img.convert("-Oraw", self.filename, dstfn)

    def exists(self):
        return self.filename and os.path.exists(self.filename)


class Operation():
    cmd = None
    args = None

    def __init__(self, args):
        self.args = args

    def apply(self, layer):
        raise NotImplementedError

    def __str__(self):
        return "%s(%r)" % (self.cmd, self.args)

    def __repr__(self):
        return "<%s 0x%x />" % (self, id(self))


class FromOperation(Operation):
    cmd = "FROM"

    def _guess_tmpl(self, args):
        # Works for i.e. fedora:23
        return args.replace(":", "-")

    def apply(self, layer):
        tmpl = self._guess_tmpl(self.args)
        layer.name = tmpl + ".qcow2"
        log.debug("Checking presence: %s" % layer.filename)
        if os.path.exists(layer.filename):
            log.debug("Reusing base %s" % layer)
        else:
            log.info("Fetching new base %s" % layer.name)
            builder("--format=qcow2", "-o", layer.filename, tmpl)
            log.debug("Created base %s" % layer)
        return layer


class RunOperation(Operation):
    cmd = "RUN"
    env = []

    def apply(self, layer):
        env = " ".join(self.env)
        cmd = "export %s ; %s" % (env, self.args)

        log.debug("Run: %s" % cmd)

        fish(layer.filename,
             "sh", cmd)


class CmdOperation(Operation):
    cmd = "CMD"
    env = []

    def apply(self, layer):
        if self.args.startswith("["):
            log.warn("Not supporting CMD […], copying it anyway")

        env = ["export %s" % e for e in self.env if "=" in e]
        cmd = "#!/bin/bash\n\n%s\n\n%s" % ("\n".join(env), self.args)
        log.debug("rc.local: %s" % cmd)

        fish(layer.filename,
             "write", "/etc/rc.d/rc.local", cmd,
             ":",
             "sh", "chmod a+x /etc/rc.d/rc.local",
             ":",
             "sh", "sed -i '/^ExecStart=/ s/$/ --autologin root/' /usr/lib/systemd/system/getty@.service /usr/lib/systemd/system/serial-getty@.service",
             ":",
             "sh", "sed -i -e '/linux.*vmlinuz/ s/$/ quiet/' -e 's/timeout=[^ ]*/timeout=1/' /boot/grub2/grub.cfg",
             ":",
             "sh", "sed -i '/^SELINUX=/ s/=.*/=permissive/' /etc/sysconfig/selinux")


class ExposeOperation(Operation):
    cmd = "EXPOSE"

    def apply(self, layer):
        if not self.args.isdigit():
            log.error("Only supporting EXPOSE <port> ignoring")
            return
        fish(layer.filename,
            "sh", "firewall-offline-cmd --add-port=%s/tcp" % self.args)


class IgnoreOperation(Operation):
    def apply(self, layer):
        log.warn("Ignoring operation %s" % self.cmd)


class MaintainerOperation(IgnoreOperation):
    cmd = "MAINTAINER"


class EnvOperation(Operation):
    cmd = "ENV"

    def apply(self, layer):
        CmdOperation.env.append(self.args)
        RunOperation.env.append(self.args)


class Context():
    do_rebuild = False

    layers = None
    operations = None

    @property
    def layer(self):
        return self.layers[-1] if self.layers else None

    @layer.setter
    def layer_set(self, val):
        self.layers.append(val)

    def run(self, ops):
        for op in ops:
            self.apply(op)
        return self.layer

    def apply(self, op):
        log.debug("Applying to context %s: %s" % (self, op))
        log.info(" %s" % op)

        if self.layers is None:
            log.debug("Initializing first image")
            self.layers = []
            new_layer = Layer()
            op.apply(new_layer)
        else:
            new_layer = self.layer.derive_for_op(op)

            do_build = self.do_rebuild or not new_layer.exists()
            log.debug("Build layer: %s" % do_build)
            if do_build:
                new_layer.create()
                op.apply(new_layer)

        self.layers.append(new_layer)
        log.info(" -> %s" % new_layer)

    def tag(self, name):
        self.layer.derive(name).create()
        return name


class OpParser():
    known_ops = [
        FromOperation,
        RunOperation,
        CmdOperation,
        MaintainerOperation,
        EnvOperation,
        ExposeOperation]

    def parse(self, data):
        known_ops_map = dict((op.cmd, op) for op in self.known_ops)
        parsed_ops = []
        data = data.replace("\\\n", "")
        for line in data.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            log.debug("Parsing line: %s" % line)
            cmd, args = line.split(" ", 1)
            try:
                op = known_ops_map[cmd]
                parsed_ops.append(op(args))
            except:
                log.exception("Unknown op: %s" % cmd)

        return parsed_ops


def run():
    def do_build(args):
        log.info("Building")

        p = OpParser()
        with open(args.file) as vockerfile:
            ops = p.parse(vockerfile.read())

        log.debug(ops)

        ctx = Context()
        ctx.do_rebuild = args.force_rm
        log.debug(ctx.run(ops))

        if args.tag:
            log.info("Tagging as %s" % args.tag)
            print(ctx.tag(args.tag))

    def do_export(args):
        log.info("Exporting %s to %s", args.IMAGE, args.file)

        image = Layer()
        image.name = args.IMAGE
        image.export(args.file)

    def do_run(args):
        log.info("Instanciating %s as %s" % (args.IMAGE, args.name))

        diskname = args.IMAGE + "-" + args.name
        image = Layer()
        image.name = args.IMAGE
        disk = image.derive(diskname)
        disk.create()
        if args.net != "user":
            args.net = "network=%s" % args.net

        # FIXME set the hostname inside the VM
        if args.hack_hostname:
            fish(disk.filename, "write", "/etc/hostname", args.name)

        xml = virt_install("--name", args.name,
                     "--memory", args.memory,
                     "--vcpus", "4",
                     "--metadata", "description=vocker/%s" % args.name,
                     "--import",
                     "--disk", disk.filename,
                     "--network", args.net,
                     "--graphics", "spice",
                     "--memballoon", "model=virtio",
                     "--rng", "/dev/random",
                     "--noautoconsole",
                     "--print-xml")

        # Decode it right away
        xml = str(xml).encode("UTF-8")

        if args.publish:
            hostport, innerport = args.publish.split(":")

            def random_mac():
                """Generate a random mac
                """
                mac = [0x00, 0x16, 0x3e,
                       random.randint(0x00, 0x7f),
                       random.randint(0x00, 0xff),
                       random.randint(0x00, 0xff)]
                return ':'.join(map(lambda x: "%02x" % x, mac))

            domroot = ET.fromstring(xml)

            # Needed to make guest ssh port accessible from the outside
            # http://blog.vmsplice.net/2011/04/
            # how-to-pass-qemu-command-line-options.html
            ET.register_namespace("qemu", "http://libvirt.org/"
                                  "schemas/domain/qemu/1.0")
            snippet = ET.fromstring("""
            <qemu:commandline
             xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0">
            <qemu:arg value='-redir'/>
            <qemu:arg value='tcp:{hostport}::{innerport}'/>
            <qemu:arg value='-netdev'/>
            <qemu:arg value='socket,id=busnet0,mcast=230.0.0.1:1234'/>
            <qemu:arg value='-device'/>
            <qemu:arg value='virtio-net-pci,netdev=busnet0,mac={mac}'/>
            </qemu:commandline>
            """.format(hostport=hostport, innerport=innerport,
                       mac=random_mac()))
            domroot.append(snippet)

            xml = ET.tostring(domroot)

        with tempfile.NamedTemporaryFile("wb") as spec:
            spec.write(xml)
            spec.flush()
            sh.virsh("define", spec.name)
            sh.virsh("start", args.name)

        print(args.name)

        if args.i:
            _attach(args.name)

        if args.rm:
            _rm(args.name)

    def do_attach(args):
        _attach(args.NAME)

    def _attach(name):
        child_pid = os.fork()
        if child_pid == 0:
            os.execv("/usr/bin/virsh", ["/usr/bin/virsh", "console", name])
        os.waitpid(child_pid, 0)

    def do_rm(args):
        _rm(args.NAME)

    def _rm(name):
        log.info("Removing %s" % name)
        try:
            sh.virsh("destroy", name)
        except:
            pass
        sh.virsh("undefine", name)

    def do_add_network(args):
        log.info("Adding network %s" % args.NAME)
        print(args.subnet.netmask)
        netmask = args.subnet.netmask
        network_ip = args.subnet.network_address
        broadcast_ip = args.subnet.broadcast_address

        def_string = """
      <network>
        <name>%s</name>
        <bridge name="vocker-%s" />
        <ip address="%s" netmask="%s">
          <dhcp>
            <range start="%s" end="%s" />
          </dhcp>
        </ip>
      </network>
                    """ % (args.NAME,
                           args.NAME,
                           network_ip + 1,
                           netmask,
                           network_ip + 2,
                           broadcast_ip - 1)
        with tempfile.NamedTemporaryFile(delete=True) as net_def:
            net_def.write(def_string.encode())
            net_def.flush()
            print(sh.virsh("net-create", net_def.name))

    def do_rm_network(args):
        log.info("Removing network %s" % args.NAME)
        print(sh.virsh("net-destroy", args.NAME))

    def do_list_networks(args):
        print(sh.virsh("net-list"))

    try:
        os.makedirs(IMAGES_DIR)
    except OSError as e:
        if e.errno != errno.EEXIST:
            log.error(e)
            exit(1)
    log.debug("Using images dir: %s" % IMAGES_DIR)

    argparser = argparse.ArgumentParser(description='Vocker!')

    argparser.add_argument("--debug", action="store_true")

    subparsers = argparser.add_subparsers()
    build = subparsers.add_parser("build",
                                  help="Build an image")
    build.add_argument("SOURCE", nargs="?",
                       type=argparse.FileType('r'),
                       default=sys.stdin)
    build.add_argument("--tag", "-t", nargs="?",
                       help="Give the image a name")
    build.add_argument("--force-rm", action="store_true")
    build.add_argument("--file", "-f", default="Dockerfile")
    build.set_defaults(func=do_build)

    export = subparsers.add_parser("export",
                                    help="Export an image")
    export.add_argument("--file", "-f", nargs=1)
    export.add_argument("IMAGE")
    export.set_defaults(func=do_export)

    run = subparsers.add_parser("run",
                                help="Create a VM from an image")
    run.add_argument("--name", default=namegen())
    run.add_argument("--rm", action="store_true")
    run.add_argument("-i", action="store_true")
    run.add_argument("--net", default="user")
    run.add_argument("--publish", "-p", help="Publish a port (hostport:innerport)")
    run.add_argument("-t", action="store_true")
    run.add_argument("--hack-hostname", action="store_true",
                     help="Hack: Slowing down run, but sets hostname")
    run.add_argument("--memory", "-m", default="1024",
                     help="Amount of memory to allow")
    run.add_argument("IMAGE")
    run.set_defaults(func=do_run)

    attach = subparsers.add_parser("attach",
                                help="Attach to a VM")
    attach.add_argument("NAME")
    attach.set_defaults(func=do_attach)

    rm = subparsers.add_parser("rm",
                               help="Destroy a VM")
    rm.add_argument("NAME")
    rm.set_defaults(func=do_rm)

    network = subparsers.add_parser("network",
                                    help="Manage networks")

    network_subparsers = network.add_subparsers()
    add_network = network_subparsers.add_parser("add",
                                                help="Add a network")
    add_network.add_argument("NAME")
    add_network.add_argument("--subnet", default=subnetgen(), type=ipaddress.IPv4Network)
    add_network.set_defaults(func=do_add_network)
    rm_network = network_subparsers.add_parser("rm",
                                               help="Destroy a network")
    rm_network.add_argument("NAME")
    rm_network.set_defaults(func=do_rm_network)

    ls_network = network_subparsers.add_parser("ls",
                                               help="Show networks")
    ls_network.set_defaults(func=do_list_networks)

    args = argparser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if "func" in args:
        args.func(args)

if __name__ == "__main__":
    run()
