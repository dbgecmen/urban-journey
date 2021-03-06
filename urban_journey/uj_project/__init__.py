import os
from os import symlink, mkdir
from os.path import join, isdir, isabs, isfile, relpath, basename, normpath, islink
from shutil import copyfile, move
import subprocess
from collections import defaultdict
import pip
import importlib.util
import importlib.machinery
import inspect
import unittest
from time import sleep

import yaml  # PyYAML

from urban_journey import __version__ as uj_version, node_register, update_plugins, NodeBase
from urban_journey.common.rm import rm
from urban_journey import plugins as plugins_module
from urban_journey import plugin_tests as plugin_tests_module


# Open letter to past Aaron.
#
# Dear past Aaron,
#
# Your'e an idiot. This is what happens when you start writing code without
# thinking or even knowing what it should do in the end. This kind of code
# should only exist in the purgatory repository. Please in the future make
# sure you have a plan and refrain your'e self from using 'neat' tricks and
# buen code.
#
#
# Cheers,
# Nov 2016 Aaron


# Open letter to Microsoft.
#
# Dear Microsoft,
#
# Fuck you.
#
#
# Cheers,
# Aaron


# Check whether git is available and import gitpython if it is.
try:
    subprocess.run(["git", "--version"], stdout=subprocess.PIPE)
    from git import Repo
    from git.exc import InvalidGitRepositoryError, RepositoryDirtyError, UnmergedEntriesError
    git_available = True
except OSError:
    git_available = False

empty_project_dir = os.path.join(os.path.dirname(__file__), "empty_project")


class InvalidUjProjectError(Exception):
    """
    This exception is raised if the target directory is not in a valid uj project.
    """
    pass


class PluginsMissingError(Exception):
    """
    This exception is raised if the uj project is missing one or more plugins.
    """
    pass


class UjProject:
    """
    This class can be use to interact with a urban journey project.

    :param string path: directory holding the uj project.
    :param urban_journey.UjProject parent_project: If not None. This project will be opened
       as a plugin for the parent_project.
    :param int verbosity: Set the verbosity for the :class:`unittest.TextTestRunner` used to
       unittest the project.
    :param bool istest: If True, load the unit testing nodes.
    """

    def __init__(self, path=None, parent_project=None, verbosity=0, is_test=False):
        # Find project root folder
        self.path = self.find_project_root(os.path.abspath(path or os.getcwd()))  #: Project root directory.
        self.parent_project = parent_project  #: The parent project if this project is opened as a plugin.

        if self.path is None:
            raise InvalidUjProjectError("error: Not a uj project (or any of the parent directories)")

        # Check if this is a valid uj project.
        self.check_validity()

        self.verbosity = verbosity  #: Verbosity for the :class:`unittest.TextTestRunner` used to unittest the project.
        self.__name = None
        self.__plugins = None
        self.__python_dependencies = None
        self.__version = None
        self.__author = ""
        self.__plugins_updated = False
        self.__nodes = None

        self.is_test = is_test  #: If True, the unit testing nodes are also loaded.

        self.update_handlers = {
            "git": self.update_git,
            "symlink": self.update_symlink,
            "web": self.update_web,
            "zip": self.update_zip,
            "copy": self.update_copy,
        }  #: Dictionary holding the handlers for each type of code source.

        # Create plugins folder if it doesn't exist.
        if not isdir(join(self.path, "plugins")):
            mkdir(join(self.path, "plugins"))

        # Create plugins/.gitignore if it doesn't exist.
        if not isfile(join(self.path, "plugins", ".gitignore")):
            with open(join(self.path, "plugins", ".gitignore"), "w") as f:
                f.write("*\n!.gitignore")

        self.load_project()

    def print(self, *args):
        """
        Print function that will only print if the verbosity is non-zero.
        :param args:
        :return:
        """
        if self.verbosity:
            print(*args)

    def check_validity(self):
        """Checks whether this is a valid uj project."""
        if not isdir(join(self.path, ".uj")):
            raise InvalidUjProjectError("error: Missing '.uj' directory.")

        if not isdir(join(self.path, "src")):
            raise InvalidUjProjectError("error: Missing 'src' directory")

        if not isfile(join(self.path, "config.yaml")):
            raise InvalidUjProjectError("error: Missing 'config.yaml'")

        if not isfile(join(self.path, "src", "__init__.py")):
            raise InvalidUjProjectError("error: Missing 'src/__init.py'")

        if not isfile(join(self.path, "src", "main.py")):
            raise InvalidUjProjectError("error: Missing 'src/main.py'")

        return True

    @property
    def plugins(self):
        """List of plugins in the project."""
        return self.__plugins

    @property
    def python_dependencies(self):
        """List of python dependencies for the project."""
        return self.__python_dependencies

    @property
    def nodes(self):
        """List of nodes in the project."""
        return self.__nodes

    @property
    def name(self):
        """The name of the project."""
        return self.__name

    @property
    def plugins_updated(self):
        """True if all plugins are present."""
        return self.__plugins_updated

    def get_metadata(self):
        """
        Load in the project metadata file.
        :return: Dictionary with the metadata.
        """
        if isfile(join(self.path, ".uj", "plugin_metadata.yaml")):
            with open(join(self.path, ".uj", "plugin_metadata.yaml"), "r") as f:
                data = yaml.load(f) or {}
            return data
        else:
            return {}

    def set_metadata(self, value):
        """
        Save the metadata to it's file.

        :param value: Dictionary with the metadata.
        """
        with open(join(self.path, ".uj", "plugin_metadata.yaml"), "w") as f:
            yaml.dump(value, f)

    @property
    def version(self):
        """The project version."""
        return self.__version

    @property
    def author(self):
        """The project author."""
        return self.__author

    @staticmethod
    def init(path=None):
        """Creates an empty uj project. If possible and not existing, it initializes a git repository."""
        # Initialize current directory if no arguments where given.
        target_directory = path or "./"

        # Walk through empty source directory and copy any non existing files.
        for (dir_path, dir_names, file_names) in os.walk(empty_project_dir):
            # Get relative path to source root.
            rel_path = os.path.relpath(dir_path, empty_project_dir)
            # Get path to current target directory
            target_path = os.path.normpath(os.path.join(target_directory, rel_path))
            # Create target directory if necessary.
            if not os.path.isdir(target_path):
                os.mkdir(target_path)
            # Create file id necessary.
            for file_name in file_names:
                if not os.path.exists(os.path.join(target_path, file_name)):
                    copyfile(os.path.join(dir_path, file_name), os.path.join(target_path, file_name))
                # If it's copying a ujml file. Fill is the version number.
                if file_name.endswith(".ujml"):
                    with open(os.path.join(target_path, file_name), "r") as f:
                        content = f.read()
                    with open(os.path.join(target_path, file_name), "w") as f:
                        f.write(content.format(version=uj_version))

        # If possible make sure it's a git repository.
        if git_available:
            try:
                Repo(target_directory)
            except InvalidGitRepositoryError:
                Repo.init(target_directory)

    def plugin_projects(self):
        """Generator yielding a :class:`urban_journey.UjProject` instance for each plugin in the project."""
        for entry in os.scandir(join(self.path, "plugins")):
            if entry.is_dir():
                try:
                    yield UjProject(entry.path, self)
                except InvalidUjProjectError:
                    continue

    def load_project(self):
        """(Re)loads the project. Returns True if all plugins are satisfied."""

        with open(join(self.path, "config.yaml"), "rb") as f:
            config = yaml.load(f)

        self.__plugins = defaultdict(list, config.pop('plugins', {}) or {})
        self.__python_dependencies = config.pop('dependencies', []) or []
        self.__version = config.pop('version', None)
        self.__author = config.pop('author', '')
        self.__name = config.pop('name', None) or basename(normpath(self.path))

        if self.parent_project is None:
            # Get plugins from plugins.
            for entry in os.scandir(join(self.path, "plugins")):
                if entry.is_dir():
                    try:
                        # Load in plugin project
                        d_project = UjProject(entry.path, self)
                        for name, sources in d_project.plugins.items():
                            for source in sources:
                                if source not in self.plugins[name]:
                                    self.plugins[name].append(source)
                        for pd in d_project.python_dependencies:
                            if pd not in self.python_dependencies:
                                self.python_dependencies.append(pd)
                    except InvalidUjProjectError:
                        pass

        # Print warning for missing python plugins
        installed = [i.key for i in pip.get_installed_distributions()]
        for package in self.python_dependencies:
            if package not in installed:
                self.print("WARNING: Python package dependency '{}' missing.".format(package))

        # Check for missing plugins
        self.create_symlinks()
        if self.parent_project is None:
            plugin_symlinks = join(self.path, '.uj', 'plugin_symlinks')
        else:
            plugin_symlinks = join(self.parent_project.path, '.uj', 'plugin_symlinks')

        # Check if all plugins have been loaded. Any newly added plugins, might have unsatisfied plugins.
        # So you might want to run this function again.
        for name in self.plugins:
            if not islink(join(plugin_symlinks, name)):
                self.__plugins_updated = False
                return False

        self.__plugins_updated = True
        return True

    def load_nodes(self):
        """
        Loads all nodes in the project.
        """

        self.load_project()
        if not self.plugins_updated:
            raise PluginsMissingError("error: Plugin(s) missing. Run 'uj list' to see which plugins are missing and "\
                                      "'uj update' to fetch missing plugins.")

        # Loads in project nodes.
        self.__nodes = {}
        if isfile(join(self.path, "src", "nodes.py")):
            # Import nodes module and scan it for nodes
            nodes_module = importlib.import_module("urban_journey.plugins.{}.nodes".format(self.name))
            for member_name, member in inspect.getmembers(nodes_module):
                # Ignore all private members
                if member_name.startswith('__'):
                    continue
                # Add the member to the node register if it's a node.
                if isinstance(member, type):
                    if issubclass(member, NodeBase):
                        self.__nodes[member_name] = member

        # Loads in test nodes
        if isfile(join(self.path, "test", "nodes.py")) and self.is_test:
            # Import nodes module and scan it for nodes
            nodes_module = importlib.import_module("urban_journey.plugin_tests.{}.nodes".format(self.name))
            for member_name, member in inspect.getmembers(nodes_module):
                # Ignore all private members
                if member_name.startswith('__'):
                    continue
                # Add the member to the node register if it's a node.
                if isinstance(member, type):
                    if issubclass(member, NodeBase):
                        self.__nodes[member_name] = member

        if self.parent_project is None:
            for plugin in self.plugin_projects():
                plugin.load_nodes()
                for name, node in plugin.nodes.items():
                    self.__nodes[name] = node

    def create_symlinks(self):
        """
        Creates a symlink for the project source and plugins to a location accasible to the
        """
        # Make sure '.uj/plugin_symlinks' directory exists
        # Make sure that the project src is symlinked in '.uj/plugin_symlinks'
        # Make sure that '.uj/plugin_symlinks' is in the plugin_module path.
        # Make sure that plugins src is symlinked in '.uj/plugin_symlinks'.
        #
        # Does the same thing for the plugin tests.

        if self.parent_project is None:
            plugin_symlinks = join(self.path, '.uj', 'plugin_symlinks')
            plugin_tests_symlinks = join(self.path, '.uj', 'plugin_tests_symlinks')
        else:
            plugin_symlinks = join(self.parent_project.path, '.uj', 'plugin_symlinks')
            plugin_tests_symlinks = join(self.parent_project.path, '.uj', 'plugin_tests_symlinks')

        if not isdir(plugin_symlinks):
            os.mkdir(plugin_symlinks)

        if not isdir(plugin_tests_symlinks):
            os.mkdir(plugin_tests_symlinks)

        rm(join(plugin_symlinks, self.name))
        symlink(relpath(join(self.path, 'src'), plugin_symlinks), join(plugin_symlinks, self.name))

        rm(join(plugin_tests_symlinks, self.name))
        symlink(relpath(join(self.path, 'test'), plugin_tests_symlinks), join(plugin_tests_symlinks, self.name))

        if self.parent_project is None:
            if plugin_symlinks not in plugins_module.__path__:
                plugins_module.__path__.append(plugin_symlinks)

            if plugin_tests_symlinks not in plugin_tests_module.__path__:
                plugin_tests_module.__path__.append(plugin_tests_symlinks)

            for plugin in self.plugin_projects():
                rm(join(plugin_symlinks, plugin.name))
                symlink(relpath(join(plugin.path, 'src'), plugin_symlinks), join(plugin_symlinks, plugin.name))

                rm(join(plugin_tests_symlinks, plugin.name))
                symlink(relpath(join(plugin.path, 'test'), plugin_tests_symlinks), join(plugin_tests_symlinks, plugin.name))

    def update(self, *args, force=False):
        """Updates all plugins in the project."""
        if len(args):
            for arg in args:
                if arg in self.plugins:
                    self.update_plugin(arg, self.plugins[arg], force)
                else:
                    self.print("WARNING: No plugin named '{}'".format(arg))
        else:
            while True:
                for name, sources in self.plugins.items():
                    self.update_plugin(name, sources, force)
                if self.load_project():
                    return

    def update_plugin(self, name, sources, force):
        """Updates a particular plugin in the project."""
        dm = self.get_metadata()
        target_dir = join(self.path, "plugins", name)

        # Try to use last used source.
        if name in dm and isdir(target_dir):
            if self.update_handlers[dm[name][0]](name, dm[name][1], force):
                return True

        # Last used source failed, try other sources
        for method, source in sources:
            if self.update_handlers[method](name, source, force):
                dm[name] = [method, source]
                self.set_metadata(dm)
                return True

        self.print("Unable to update plugin '{}'.".format(name))
        return False

    def run(self):
        """Run the project."""
        if not self.plugins_updated:
            raise PluginsMissingError("error: Plugin(s) missing. Run 'uj list' to see which plugins are missing and "
                                      "'uj update' to fetch missing plugins.")

        # Add default nodes to node register.
        update_plugins()

        # Loads in the plugin nodes.
        self.load_nodes()

        # Add plugin nodes to node register.
        for name, node in self.nodes.items():
            if node not in node_register.values():
                node_register[name] = node

        # Import main function
        main = importlib.import_module("urban_journey.plugins.{}.main".format(self.name)).main
        old_cwd = os.getcwd()
        os.chdir(join(self.path, "src"))
        main([])
        os.chdir(old_cwd)

    def test(self, verbosity=None):
        """
        Run the unittests in the project.
        :param int verbosity: Verbosity passed to the instance :class:`unittest.TextTestRunner` use to run the
           unittests.
        """
        if not self.plugins_updated:
            raise PluginsMissingError("error: Plugin(s) missing. Run 'uj list' to see which plugins are missing and "
                                      "'uj update' to fetch missing plugins.")

        # Add default nodes to node register.
        update_plugins()

        # Loads in the plugin nodes.
        self.load_nodes()

        # Add plugin nodes to node register.
        for name, node in self.nodes.items():
            if node not in node_register.values():
                node_register[name] = node

        # Find all unittests
        test_package = importlib.import_module("urban_journey.plugin_tests.{}".format(self.name))
        test_suit = unittest.defaultTestLoader.discover(test_package.__path__[0], )

        # TODO: Run plugin unit tests.

        verbosity = verbosity or self.verbosity

        test_runner = unittest.TextTestRunner(verbosity=verbosity)
        test_runner.run(test_suit)

    def clear(self):
        rm(join(self.path, '.uj', 'plugin_metadata.yaml'))
        rm(join(self.path, '.uj', 'plugin_symlinks'))
        for name in self.plugins:
            rm(join(self.path, 'plugins', name))

    @staticmethod
    def find_project_root(path):
        """
        Finds the root directory of the project, in case path is a subdirectory of the project.
        This function does not guarantee that the returned directory is a valid uj project. Use
        :func:`urban_journey.UjProject.check_validity` to check this.

        :returns: Path to the project root. If the root path is not found, ``None`` is returned.
        :rtype: string
        """

        # Check whether path is  directory.
        if not isdir(path):
            return None
        prev_path = None

        # Loop until the path doesn't change anymore. This means that we have reached the file system's root directory
        # and thus path is not inside a valid uj project.

        while path != prev_path:
            # Check whether path contains the ".uj" directory. If it does, this is the project root directory.
            # However this does not guarantee that this is a valid uj project. Use ``check_validity`` to check this.
            if os.path.isdir(os.path.join(path, ".uj")):
                return path

            # Not the project root. So step one directory higher and try again.
            prev_path = path
            path = os.path.normpath(os.path.join(path, '..'))

    # Loads plugins into project.
    def update_git(self, name, source, force):
        """
        Updates plugin loaded from a git repository. If it has already been cloned, the repository is pulled.
        Otherwise it's cloned.

        :param string name: The plugin name.
        :param string source: Source url with the git repository.
        :param bool force: If ``True`` the repository will always be cloned.
        :returns: ``True`` if successful.
        :rtype: bool
        """
        # Check if git is available on this computer.
        if git_available:
            target_dir = join(self.path, "plugins", name)

            # Clone if the plugin doesn't exist or is being forced. Otherwise try pulling
            if not isdir(target_dir) or force:
                return self.git_clone(name, source)
            else:
                return self.git_pull(name, source)
        else:
            # No git os this computer.
            return False

    def git_clone(self, name, source):
        """
        Clone the plugin from git repository.

        :param name: Plugin name.
        :param source: Source url.
        :returns: ``True`` if successful.
        :rtype: bool
        """
        if git_available:
            target_dir = join(self.path, "plugins", name)
            temp_dir = join(self.path, "plugins", "temp_" + name)

            try:
                # Clone repository to temporary folder
                repo = Repo.clone_from(source, temp_dir)
                self.print("cloned '{}' from '{}'".format(name, source))
            except:
                return False

            # Check if valid uj project.
            try:
                UjProject(temp_dir, self)
            except InvalidUjProjectError:
                return False

            # Delete old version of project if exiting
            rm(target_dir)

            # Move temp dir to target location and clean.
            move(temp_dir, target_dir)
            rm(temp_dir)
            return True
        else:
            return False

    def git_pull(self, name, source):
        """
        Pull the plugin from  git repository.

        :param name: Plugin name.
        :param source: Source url.
        :returns: ``True`` if successful.
        :rtype: bool
        """
        target_dir = join(self.path, "plugins", name)
        try:
            repo = Repo(target_dir)
            try:
                repo.remote().pull()
                self.print("pulled '{}' from '{}'".format(name, source))
                return True
            except RepositoryDirtyError:
                self.print("WARNING: Repository for plugin '{}' is dirty.".format(name))
                return True
            except UnmergedEntriesError:
                self.print("WARNING: Repository for plugin '{}' has unmerged changes.".format(name))
                return True
        except InvalidGitRepositoryError:
            # This is an invalid git repository. Clone it.
            return self.git_clone(name, source)

    def update_symlink(self, name, source, force):
        """
        Load in a plugin by creating a symlink to it.

        :param name: Plugin name.
        :param source: Source path.
        :param bool force: Delete any existing symlink and recreate it.
        :returns: ``True`` if successful.
        :rtype: bool
        """
        target_dir = join(self.path, "plugins", name)

        # Only update if the plugin doesn't exist or is being forced.
        if not force and isdir(target_dir):
            return True

        # If source dir path is relative, get absolute path relative to the project root.
        if not isabs(source):
            source = join(self.path, source)

        # Check if source dir exists.
        if not isdir(source):
            return False

        # Check if source dir is a valid uj project.
        try:
            UjProject(source, None)
        except InvalidUjProjectError:
            return False

        rm(target_dir)

        symlink(relpath(source, join(self.path, "plugins")), target_dir, target_is_directory=True)
        self.print("created symlink '{}' with source '{}'".format(name, target_dir))
        return True

    # TODO: Implement web, zip and copy plugin source handlers.

    def update_web(self, name, source, force):
        """
        Download and extract zip file from the web.

        :param name: Plugin name.
        :param source: Source url.
        :param bool force: Delete any existing code and reload it.
        :returns: ``True`` if successful.
        """
        raise NotImplementedError()

    def update_zip(self, name, source, force):
        """
        Extract local zip file.

        :param name: Plugin name.
        :param source: Source path.
        :param bool force: Delete any existing code and re-extract it.
        :returns: ``True`` if successful.
        """
        raise NotImplementedError()

    def update_copy(self, name, source, force):
        """
        Copy plugin from local folder.

        :param name: Plugin name.
        :param source: Source path.
        :param bool force: Delete any existing code and recopy it.
        :returns: ``True`` if successful.
        """
        raise NotImplementedError()
