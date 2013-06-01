import os
import sys
import py
import argparse
import subprocess
from devpi.util.lazydecorator import lazydecorator
from devpi.util import url as urlutil
from devpi import log, cached_property
from devpi.config import Config
import requests
import json
std = py.std
subcommand = lazydecorator()

def main(argv=None):
    if argv is None:
        argv = list(sys.argv)
    args = parse_args(argv)
    mod = args.mainloc
    func = "main"
    if ":" in mod:
        mod, func = mod.split(":")
    mod = __import__(mod, None, None, ["__doc__"])
    hub = Hub(args)
    return getattr(mod, func)(hub, args)

class Hub:
    LOGINPATH = py.path.local(os.path.expanduser("~/.devpi/login"))

    class Popen(std.subprocess.Popen):
        STDOUT = std.subprocess.STDOUT
        PIPE = std.subprocess.PIPE
        def __init__(self, cmds, *args, **kwargs):
            cmds = [str(x) for x in cmds]
            std.subprocess.Popen.__init__(self, cmds, *args, **kwargs)

    def __init__(self, args):
        self._tw = py.io.TerminalWriter()
        self.args = args
        self.cwd = py.path.local()

    @property
    def clientdir(self):
        return py.path.local(self.args.clientdir)

    @cached_property
    def http(self):
        session = requests.session()
        if self.LOGINPATH.check():
            data = json.loads(self.LOGINPATH.read())
            session.auth = data["user"], data["password"]
        return session

    def update_auth(self, user, password):
        self.http.auth = (user, password)
        oldumask = os.umask(0077)
        self.LOGINPATH.write(json.dumps(dict(user=user, password=password)))
        os.umask(oldumask)

    def get_index_url(self, indexname):
        assert self.http.auth[0]
        userurl = self.config.getuserurl(self.http.auth[0])
        return urlutil.joinpath(userurl + "/", indexname)

    def raw_input(self, msg):
        return raw_input(msg)


    def getdir(self, name):
        return self._workdir.mkdir(name)

    @property
    def _workdir(self):
        try:
            return self.__workdir
        except AttributeError:
            self.__workdir = py.path.local.make_numbered_dir(prefix="devpi")
            self.info("created workdir", self.__workdir)
            return self.__workdir

    @cached_property
    def config(self):
        self.clientdir.ensure(dir=1)
        path = self.clientdir.join("config.json")
        return Config(path)

    @property
    def remoteindex(self):
        try:
            return self._remoteindex
        except AttributeError:
            from devpi.remoteindex import RemoteIndex
            self._remoteindex = RemoteIndex(self.config)
            return self._remoteindex

    @property
    def path_venvbase(self):
        path = os.environ.get("WORKON_HOME", None)
        if path is None:
            return
        return py.path.local(path)

    def popen_output(self, args, cwd=None):
        if isinstance(args, str):
            args = std.shlex.split(args)
        assert args[0], args
        args = [str(x) for x in args]
        if cwd == None:
            cwd = self.cwd
        self.line("%s$" % cwd, " ".join(args), "[to-pipe]")
        return subprocess.check_output(args, cwd=str(cwd))

    def popen_check(self, args):
        assert args[0], args
        args = [str(x) for x in args]
        self.line("$", " ".join(args))
        return subprocess.check_call(args)

    def line(self, *msgs, **kwargs):
        msg = " ".join(map(str, msgs))
        self._tw.line(msg, **kwargs)

    def debug(self, *msg):
        if self._debug:
            self.line("[debug]", *msg)

    def error(self, *msg):
        self.line(*msg, red=True)

    def fatal(self, *msg):
        self.line(*msg, red=True)
        raise SystemExit(1)

    def info(self, *msg):
        self.line(*msg, bold=True)


def parse_args(argv):
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])
    add_generic_options(parser)
    subparsers = parser.add_subparsers()

    for func, args, kwargs in subcommand.discover(globals()):
        subparser = subparsers.add_parser(func.__name__, help=func.__doc__)
        subparser.Action = argparse.Action
        func(subparser)
        mainloc = args[0]
        subparser.set_defaults(mainloc=mainloc)

    args = parser.parse_args(argv[1:])
    return args

def add_generic_options(parser):
    parser.add_argument("--debug", action="store_true",
        help="show debug messages")
    parser.add_argument("--clientdir", action="store", metavar="DIR",
        default=os.path.expanduser(os.environ.get("DEVPI_CLIENTDIR",
                                                  "~/.devpi/client")),
        help="directory for storing login and other state")

@subcommand("devpi.config")
def config(parser):
    """ show, create or delete configuration information. """
    parser.add_argument("--delete", action="store_true",
        help="delete currently stored API information")
    parser.add_argument("indexurl", metavar="URL", type=str,
        action="store", nargs="*",
        help="url for retrieving index API information. ")

@subcommand("devpi.user")
def user(parser):
    """ add, remove, modify, list user configuration"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true",
        help="create a user")
    group.add_argument("-d", "--delete", action="store_true",
        help="delete a user")
    group.add_argument("-m", "--modify", action="store_true",
        help="modify user settings")
    group.add_argument("-l", "--list", action="store_true",
        help="list existing users and their indexes")
    parser.add_argument("-p", "--password", action="store", metavar="PASS",
        type=str, default=None,
        help="password for the given user")
    parser.add_argument("username", type=str, action="store", nargs="?",
        help="user name")
    parser.add_argument("email", type=str, action="store", default=None,
        nargs="?",
        help="email address")

@subcommand("devpi.login")
def login(parser):
    """ login to devpi-server"""
    parser.add_argument("username", action="store", default=None,
                        help="username to use for login")

@subcommand("devpi.index:indexadd")
def index(parser):
    """ create, delete and manage indexes. """
    parser.add_argument("indexname", type=str, action="store",
        help="index name, specified as NAME")


@subcommand("devpi.upload.upload")
def upload(parser):
    """ prepare and upload packages to the current index. """
    parser.add_argument("-l", dest="showstatus",
        action="store_true", default=None,
        help="show remote versions, local version and package types")
    parser.add_argument("--ver", dest="setversion",
        action="store", default=None,
        help="set version to fill into setup.py and package files")
    #parser.add_argument("-y", dest="yes",
    #    action="store_true", default=None,
    #    help="answer yes on interactive questions. ")

@subcommand("devpi.test.test")
def test(parser):
    """ download and test a package against tox environments."""
    parser.add_argument("-e", metavar="VENV", type=str, dest="venv",
        default=None, action="store",
        help="virtual environment to run from the tox.ini")

    parser.add_argument("pkgspec", metavar="pkgspec", type=str,
        default=None, action="store", nargs=1,
        help="package specification to download and test")

@subcommand("devpi.push")
def push(parser):
    """ push a release and releasefiles to another index server. """
    parser.add_argument("--pypirc", metavar="path", type=str,
        default=None, action="store",
        help="path to pypirc")
    parser.add_argument("nameversion", metavar="release", type=str,
        default=None, action="store",
        help="release of format 'name-version' to push")
    parser.add_argument("posturl", metavar="url", type=str,
        default=None, action="store",
        help="post url of other index server.")


@subcommand("devpi.install")
def install(parser):
    """ install packages through current devpi index. """
    parser.add_argument("-l", action="store_true", dest="listinstalled",
        help="print list of currently installed packages. ")
    parser.add_argument("pkgspecs", metavar="pkg", type=str,
        action="store", default=None, nargs="*",
        help="uri or package file for installation from current index. """
    )


if __name__ == "__main__":
    main()
