import glob
import os
from os import system
import optparse
import sys
import shutil
import re
import random
import pinax
import pkg_resources

from optparse import make_option
from django.core.management.base import BaseCommand, CommandError

import xmlrpclib
import logging
import os
import time
import urllib2

from xmlrpclib import Fault as XMLRPCFault

EXCLUDED_PATTERNS = ('.svn',)
DEFAULT_PINAX_ROOT = None # fallback to the normal PINAX_ROOT in settings.py.
PINAX_ROOT_RE = re.compile(r'PINAX_ROOT\s*=.*$', re.M)
SECRET_KEY_RE = re.compile(r'SECRET_KEY\s*=.*$', re.M)
ROOT_URLCONF_RE = re.compile(r'ROOT_URLCONF\s*=.*$', re.M)
VIRTUALENV_BASE_RE = re.compile(r'VIRTUALENV_BASE\s*=.*$', re.M)
CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'

XML_RPC_SERVER = 'http://pypi.python.org/pypi'

class ProxyTransport(xmlrpclib.Transport):
    """
    Provides an XMl-RPC transport routing via a http proxy.
    
    This is done by using urllib2, which in turn uses the environment
    varable http_proxy and whatever else it is built to use (e.g. the
    windows    registry).
    
    NOTE: the environment variable http_proxy should be set correctly.
    See check_proxy_setting() below.
    
    Written from scratch but inspired by xmlrpc_urllib_transport.py
    file from http://starship.python.net/crew/jjkunce/ by jjk.
    
    A. Ellerton 2006-07-06
    """

    def request(self, host, handler, request_body, verbose):
        '''Send xml-rpc request using proxy'''
        #We get a traceback if we don't have this attribute:
        self.verbose = verbose
        url = 'http://' + host + handler
        request = urllib2.Request(url)
        request.add_data(request_body)
        # Note: 'Host' and 'Content-Length' are added automatically
        request.add_header('User-Agent', self.user_agent)
        request.add_header('Content-Type', 'text/xml')
        proxy_handler = urllib2.ProxyHandler()
        opener = urllib2.build_opener(proxy_handler)
        fhandle = opener.open(request)
        return(self.parse_response(fhandle))

class CheeseShop:

    """Interface to Python Package Index"""

    def __init__(self, debug=False, no_cache=False):
        """init"""
        self.no_cache = no_cache
        self.debug = debug
        self.xmlrpc = self.get_xmlrpc_server()
        self.logger = logging.getLogger("yolk")

    def get_xmlrpc_server(self):
        """
        Returns PyPI's XML-RPC server instance
        """
        #check_proxy_setting()
        try:
            return xmlrpclib.Server(XML_RPC_SERVER, transport=ProxyTransport())
        except IOError:
            self.logger("ERROR: Can't connect to XML-RPC server: %s" \
                    % XML_RPC_SERVER)

    def search(self, spec, operator):
        '''Query PYPI via XMLRPC interface using search spec'''
        return self.xmlrpc.search(spec, operator.lower())


def get_pinax_root(default_pinax_root):
    if default_pinax_root is None:
        return os.path.abspath(os.path.dirname(pinax.__file__))
    return default_pinax_root


def get_projects_dir(pinax_root):
    return os.path.join(pinax_root, 'projects')


def get_projects(pinax_root):
    projects = []
    for item in glob.glob(os.path.join(get_projects_dir(pinax_root), '*')):
        if os.path.isdir(item):
            projects.append(item)
    return projects

try:
    WindowsError
except NameError:
    WindowsError = None

def copytree(src, dst, symlinks=False):
    """
    Backported from the Python 2.6 source tree, then modified for this script's
    purposes.
    """
    names = os.listdir(src)
    
    os.makedirs(dst)
    errors = []
    for name in names:
        ignore = False
        for pattern in EXCLUDED_PATTERNS:
            if pattern in os.path.join(src, name):
                ignore = True
        if ignore:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree(srcname, dstname, symlinks)
            else:
                shutil.copy2(srcname, dstname)
        except (IOError, os.error), why:
            errors.append((srcname, dstname, str(why)))
        except shutil.Error, err:
            errors.extend(err.args[0])
    try:
        shutil.copystat(src, dst)
    except OSError, why:
        if WindowsError is not None and isinstance(why, WindowsError):
            pass
        else:
            errors.extend((src, dst, str(why)))
    if errors:
        raise shutil.Error, errors


def update_settings(pinax_root, path, old_name, new_name):
    settings_file = open(path, 'r')
    settings = settings_file.read()
    settings_file.close()
    settings = settings.replace(old_name, new_name)
    if pinax_root is not None:
        settings = PINAX_ROOT_RE.sub("PINAX_ROOT = '%s'" % (pinax_root,),
            settings)
    new_secret_key = ''.join([random.choice(CHARS) for i in xrange(50)])
    settings = SECRET_KEY_RE.sub("SECRET_KEY = '%s'" % (new_secret_key,),
        settings)
    new_root_urlconf = '%s.urls' % new_name
    settings = ROOT_URLCONF_RE.sub("ROOT_URLCONF = '%s'" % new_root_urlconf,
        settings)
    settings_file = open(path, 'w')
    settings_file.write(settings)
    settings_file.close()


def update_rename_deploy_files(path, old_name, new_name):
    for deploy_file in glob.glob(os.path.join(path, "pinax") + '*'):
        df = open(deploy_file, 'r')
        deploy_settings = df.read()
        df.close()
        deploy_settings = deploy_settings.replace(old_name, new_name)
        df = open(deploy_file, 'w')
        df.write(deploy_settings)
        df.close()
    # fix modpython.py
    modpython_file = open(os.path.join(path, "modpython.py"), "rb")
    modpython = modpython_file.read()
    modpython_file.close()
    virtualenv_base = os.environ.get("VIRTUAL_ENV", "")
    modpython = VIRTUALENV_BASE_RE.sub('VIRTUALENV_BASE = "%s"' % virtualenv_base, modpython)
    modpython_file = open(os.path.join(path, "modpython.py"), "wb")
    modpython_file.write(modpython)
    modpython_file.close()


def is_package_project(name):
    """Return true if the package contains the
    keywords "pinax-project" in its setup.py keywords"""
    dist = pkg_resources.get_distribution(name)
    name = name.replace('-','_')
    info = []
    if dist.has_metadata('PKG-INFO'):
        info = dist.get_metadata('PKG-INFO').splitlines()
    for line in info:
        if line.find('Keywords:')==0:
            if line.find('pinax-project')>-1:
                return True
    return False         

def get_package_toplevel(name):
    name = name.replace('-','_')
    dist = pkg_resources.get_distribution(name)    
    if dist.has_metadata('top_level.txt'):
        return dist.get_metadata('top_level.txt').splitlines()[0]

def get_project_apps():
    """Find all installed packages that are pinax projects"""
    env = pkg_resources.Environment()
    projects = []
    for name in env:
#        if name=='social-commerce' or name=='social_commerce':
        if is_package_project(name):
            projects.append((name, get_package_toplevel(name)))
    return projects

def install_package(name):
    system('pip install %s' % name)

def main(default_pinax_root, project_name, destination, verbose=True, requirements=True):
    
    try:
        # check to see if the destination copies an existing module name
        __import__(destination)
    except ImportError:
        # The module does not exist so we let Pinax create it as a project
        pass
    else:
        # The module exists so we raise a CommandError and exit
        raise CommandError("'%s' conflicts with the name of an existing Python module and cannot be used as a project name. Please try another name." % destination)
    
    if os.path.exists(destination):
        raise CommandError("Files already exist at this path: %s" % (destination,))
    user_project_name = os.path.basename(destination)
    pinax_root = get_pinax_root(default_pinax_root)
    if project_name in map(os.path.basename, get_projects(pinax_root)):
        source = os.path.join(get_projects_dir(pinax_root), project_name)
    else:
        try:
            dist = pkg_resources.get_distribution(project_name)
            source = os.path.join(dist.location, get_package_toplevel(project_name))
        except:
            pypi = CheeseShop()
            pkgs = pypi.search({'keywords': 'pinax-project','name':project_name},'AND')
            if len(pkgs)==1:
                pkg = pkgs[0]
                install_package(pkg['name'])
                dist = pkg_resources.get_distribution(project_name)
                source = os.path.join(dist.location, get_package_toplevel(project_name))
            else:
                print "Project template does not exist at this path: %s" % (project_name,)
                sys.exit(0)
    #source = dist.location

    if verbose:
        print "Copying your project to its new location"
    copytree(source, destination)
    if verbose:
        print "Updating settings.py for your new project"
    update_settings(default_pinax_root, os.path.join(destination, 'settings.py'),
        project_name, user_project_name)
    if verbose:
        print "Renaming and updating your deployment files"
    update_rename_deploy_files(os.path.join(destination, 'deploy'), project_name,
        user_project_name)
    if requirements:
        requirements = os.path.join(os.getcwd(), destination, 'requirements.txt')
        if os.path.exists(requirements):
            if verbose:
                print "Installing project requirements..."
            system('pip install -r %s' % (requirements,))
    if verbose:
        print "Finished cloning your project, now you may enjoy Pinax!"



class Command(BaseCommand):
    help = "Clones a Pinax starter project to <new_project_name> (which can be a path)."
    args = "<original_project> <new_project_name>"
    
    clone_project_options = (
        make_option('-l', '--list-projects', dest='list_projects',
            action = 'store_true',
            help = 'lists the projects that are available on this system'),
        make_option('-r', '--pinax-root', dest='pinax_root',
            default = DEFAULT_PINAX_ROOT,
            action = 'store_true',
            help = 'where Pinax lives on your system (defaults to Pinax in your virtual environment)'),
        make_option('-d', '--deps', dest='requirements',
            default = True,
            action = 'store_true',
            help = 'Install the app requirements'),

        make_option('-b', '--verbose', dest='verbose',
            action = 'store_false', default=True,
            help = 'enables verbose output'),
    )
    
    option_list = BaseCommand.option_list + clone_project_options
    
    
    def handle(self, *args, **options):
        """
        Handle clone_project options and run main to perform clone_project
        operations.
        """
        if options.get('list_projects'):
            pinax_root = get_pinax_root(options.get('pinax_root'))
            print "Available Projects"
            print "------------------"
            sys.path.insert(0, get_projects_dir(pinax_root))
            for project in map(os.path.basename, get_projects(pinax_root)):
                print "%s:" % project
                about = getattr(__import__(project), '__about__', '')
                for line in about.strip().splitlines():
                    print '    %s' % line
                print
            apps = get_project_apps()
            for name, project in apps:
                print "%s:" % name
                about = getattr(__import__(project), '__about__', '')
                for line in about.strip().splitlines():
                    print '    %s' % line
                print
            print "------------------"
            print "Projects on pypi.python.org"
            print "------------------"
            pypi = CheeseShop()
            for pkg in pypi.search({'keywords': 'pinax-project'},'AND'):
                print pkg['name']
                for line in pkg['summary'].splitlines():
                    print '    %s' % line

            sys.exit(0)
        
        if not args:
            # note: --help prints full path to pinax-admin
            self.print_help("pinax-admin", "clone_project")
            sys.exit(0)
        
        try:
            destination = args[1]
        except IndexError:
            sys.stderr.write("You must provide a destination path for the cloned project.\n\n")
            # note: --help prints full path to pinax-admin
            self.print_help("pinax-admin", "clone_project")
            sys.exit(0)
        
        main(options.get('pinax_root'), args[0], destination,
            verbose = options.get('verbose'),
            requirements = options.get('requirements')
        )
        return 0

