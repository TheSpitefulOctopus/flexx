"""
Definition of the Asset class to represent JS and CSS assets, and a derived
class used as a container for one or more JSModule classes.
"""

import sys
import types
from urllib.request import urlopen, Request

from . import logger

# The pscript package does not deal with license headers,
# we add them to our assets here.
HEADER = 'Autogenerated code from Flexx. Code Subject to the BSD-2-clause license.'
HEADER = '/* %s */\n\n' % HEADER

url_starts = 'https://', 'http://'


# Although these two funcs are better off in modules.py, that causes circular refs.
def get_mod_name(ob):
    """ Get the module name of an object (the name of a module object or
    the name of the module in which the object is defined). Our naming
    differs slighly from Python's in that the module in ``foo/bar/__init__.py``
    would be named ``foo.bar.__init__``, which simplifies dependency handling
    for Flexx. Note that such modules only occur if stuff is actually defined
    in them.
    """
    if not isinstance(ob, types.ModuleType):
        ob = sys.modules[ob.__module__]
    name = ob.__name__
    if module_is_package(ob):
        name += '.__init__'
    return name


def module_is_package(module):
    """ Get whether the given module represents a package.
    """
    if hasattr(module, '__file__'):
        if module.__file__.rsplit('.', 1)[0].endswith('__init__'):
            return True
    return False


def solve_dependencies(things, warn_missing=False):
    """ Given a list of things, which each have a ``name`` and ``deps``
    attribute, return a new list sorted to meet dependencies.
    """
    assert isinstance(things, (tuple, list))
    names = [thing.name for thing in things]
    thingmap = dict([(n, t) for n, t in zip(names, things)])

    for index in range(len(names)):
        seen_names = set()
        while True:
            # Get thing name on this position, check if its new
            name = names[index]
            if name in seen_names:
                raise RuntimeError('Detected circular dependency!')
            seen_names.add(name)
            # Move deps in front of us if necessary
            for dep in thingmap[name].deps:
                if dep not in names:
                    if warn_missing:
                        logger.warn('%r has missing dependency %r' % (name, dep))
                else:
                    j = names.index(dep)
                    if j > index:
                        names.insert(index, names.pop(j))
                        break  # do this index again; the dep we just moved
            else:
                break  # no changes, move to next index
    return [thingmap[name] for name in names]

# todo: We could do (basic) minification of the JS
# but it will make the code less readable, so better do this after we've
# source maps.


class Asset:
    """ Class to represent an asset (JS or CSS) to be included on the page.
    Users will typically use ``app.assets.add_shared_asset()``, see the
    corresponding docs for details.
    """

    _counter = 0

    def __init__(self, name, source=None):

        Asset._counter += 1  # so we can sort assets by their instantiation order
        self.i = Asset._counter

        # Handle name
        if not isinstance(name, str):
            raise TypeError('Asset name must be str.')
        if name.startswith(url_starts):
            if source is not None:
                raise TypeError('Remote assets cannot have a source: %s' % name)
            source = name
            name = name.replace('\\', '/').split('/')[-1]
        if not name.lower().endswith(('.js', '.css')):
            raise ValueError('Asset name must end in .js or .css.')
        self._name = name

        # Handle source
        self._remote = False
        self._source_str = None
        self._source = source
        if source is None:
            raise TypeError('Asset needs a source.')
        elif isinstance(source, str):
            if source.startswith(url_starts):
                self._remote = True
            elif source.startswith('file://'):
                raise TypeError('Cannot specify an asset using "file://", '
                                'use http or open the file and use contents.')
            else:
                self._source_str = source
        elif callable(source):
            pass
        else:
            raise TypeError('Asset source must be str or callable.')

    def __repr__(self):
        return '<%s %r at 0x%0x>' % (self.__class__.__name__, self._name, id(self))

    @property
    def name(self):
        """ The (file) name of this asset.
        """
        return self._name

    @property
    def source(self):
        """ The source for this asset. Can be str, URL or callable.
        """
        return self._source

    @property
    def remote(self):
        """ Whether the asset is remote (client will load it from elsewhere).
        If True, the source specifies the URL.
        """
        return self._remote

    def to_html(self, path='{}', link=3):
        """ Get HTML element tag to include in the document.

        Parameters:
            path (str): the path of this asset, in which '{}' can be used as
                a placeholder for the asset name.
            link (int): whether to link to this asset:

                * 0: the asset is embedded.
                * 1: normal assets are embedded, remote assets remain remote.
                * 2: the asset is linked (and served by our server).
                * 3: (default) normal assets are linked, remote assets remain remote.
        """
        path = path.replace('{}', self.name)

        if self.name.lower().endswith('.js'):
            if self.remote and link in (1, 3):
                return "<script src='%s' id='%s'></script>" % (self.source, self.name)
            elif link in (0, 1):
                code = self.to_string()
                s = '\n' if ('\n' in code) else ''
                return "<script id='%s'>%s%s%s</script>" % (self.name, s, code, s)
            else:
                return "<script src='%s' id='%s'></script>" % (path, self.name)
        elif self.name.lower().endswith('.css'):
            if self.remote and link in (1, 3):
                t = "<link rel='stylesheet' type='text/css' href='%s' id='%s' />"
                return t % (self.source, self.name)
            elif link in (0, 1):
                code = self.to_string()
                s = '\n' if ('\n' in code) else ''
                return "<style id='%s'>%s%s%s</style>" % (self.name, s, code, s)
            else:
                t = "<link rel='stylesheet' type='text/css' href='%s' id='%s' />"
                return t % (path, self.name)
        else:  # pragma: no cover
            raise NameError('Assets must be .js or .css')

    def to_string(self):
        """ Get the string code for this asset. Even for remote assets.
        """
        if self._source_str is None:
            if callable(self._source):
                self._source_str = self._source()
                if not isinstance(self._source_str, str):
                    t = 'Source function of asset %r did not return a str, but a %s.'
                    raise ValueError(t % (self.name, self._source.__class__.__name__))
            elif self._remote:
                self._source_str = self._get_from_url(self._source)
            else:  # pragma: no cover
                assert False, 'This should not happen'
        return self._source_str

    def _get_from_url(self, url):
        if url.startswith(url_starts):
            req = Request(url, headers={'User-Agent': 'flexx'})
            return urlopen(req, timeout=5.0).read().decode()
        else:  # pragma: no cover
            raise ValueError('_get_from_url() needs a URL string.')


class Bundle(Asset):
    """ A bundle is an asset that represents a collection of Asset objects
    and JSModule objects. In the output, the source for the modules occurs
    after the sources of the assets. Dependency resolution is honoured for
    the modules, and the bundle exposes an aggregate of the dependencies,
    so that bundles can themselves be sorted.
    """

    def __init__(self, name):
        super().__init__(name, '')
        self._assets = []
        self._module_name = name.rsplit('.', 1)[0].split('-')[0]
        self._modules = []
        self._deps = set()
        self._need_sort = False

    def __repr__(self):
        t = '<%s %r with %i assets and %i modules at 0x%0x>'
        return t % (self.__class__.__name__, self._name,
                    len(self._assets), len(self._modules), id(self))

    def add_asset(self, a):
        """ Add an asset to the bundle. Assets added this way occur before the
        code for the modules in this bundle.
        """
        if not isinstance(a, Asset):
            raise TypeError('Bundles.add_asset() needs an Asset, not %s.' %
                            a.__class__.__name__)
        if isinstance(a, Bundle):
            raise TypeError('Bundles can contain assets and modules, but not bundles.')
        self._assets.append(a)

    def add_module(self, m):
        """ Add a module to the bundle. This will (lazily) invoke a
        sort of the list of modules, and define dependencies to other
        bundles, so that bundles themselves can be sorted.
        """

        ext = '.' + self.name.rsplit('.')[-1].lower()

        # Check if module belongs here
        if not m.name.startswith(self._module_name):
            raise ValueError('Module %s does not belong in bundle %s.' %
                             (m.name, self.name))

        # Add module
        self._modules.append(m)
        self._need_sort = True

        # Add deps for this module
        deps = set()
        for dep in m.deps:
            while '.' in dep:
                deps.add(dep)
                dep = dep.rsplit('.', 1)[0]
            deps.add(dep)

        # Clear deps that are represented by this bundle
        for dep in deps:
            if not (dep.startswith(self._module_name) or
                    self._module_name.startswith(dep + '.')):
                self._deps.add(dep + ext)

    @property
    def assets(self):
        """ The list of assets in this bundle (excluding modules).
        """
        return tuple(self._assets)

    @property
    def modules(self):
        """ The list of modules, sorted by name and dependencies.
        """
        if self._need_sort:
            f = lambda m: m.name
            self._modules = solve_dependencies(sorted(self._modules, key=f))
        return tuple(self._modules)

    @property
    def deps(self):
        """ The set of dependencies for this bundle, expressed in module names.
        """
        return self._deps

    def to_string(self):
        # Concatenate code strings and add TOC. Module objects do/cache the work.
        isjs = self.name.lower().endswith('.js')
        toc = []
        source = []
        for a in self.assets:
            toc.append('- asset ' + a.name)
            source.append('/* ' + (' %s ' % a.name).center(70, '=') + '*/')
            source.append(a.to_string())
        for m in self.modules:
            s = m.get_js() if isjs else m.get_css()
            toc.append('- module ' + m.name)
            source.append('/* ' + (' %s ' % m.name).center(70, '=') + '*/')
            source.append(HEADER)
            source.append(s)
        if len(self.assets + self.modules) > 1:
            source.insert(0, '/* Bundle contents:\n' + '\n'.join(toc) + '\n*/\n')
        #if isjs:
        #    source.append('window.flexx.spin(%i);' % len(self.modules))
        return '\n\n'.join(source)
