
__author__ = "desultory"
__version__ = "1.3.1"

from tomllib import load, TOMLDecodeError
from pathlib import Path
from queue import Queue

from zenlib.logging import loggify
from zenlib.util import handle_plural, pretty_print, NoDupFlatList


@loggify
class InitramfsConfigDict(dict):
    """
    Dict for containing config for the InitramfsGenerator

    IMPORTANT:
        This dict does not act like a normal dict, setitem is designed to append when the overrides are used
        Default parameters are defined in builtin_parameters

    If a new parameter is added, and it's not a known type, an exception will be raised.
    If that paramter name starts with an underscore, it will be added to a queue for later processing.
    """
    builtin_parameters = {'modules': NoDupFlatList,  # A list of the names of modules which have been loaded, mostly used for dependency checking
                          'imports': dict,  # A dict of functions to be imported into the initramfs, under their respective hooks
                          'validated': bool,  # A flag to indicate if the config has been validated, mostly used for log levels
                          'custom_parameters': dict,  # Custom parameters loaded from imports
                          'custom_processing': dict,  # Custom processing functions which will be run to validate and process parameters
                          '_processing': dict}  # A dict of queues containing parameters which have been set before the type was known

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Define the default parameters
        for parameter, default_type in self.builtin_parameters.items():
            if default_type == NoDupFlatList:
                super().__setitem__(parameter, default_type(no_warn=True, log_bump=5, logger=self.logger, _log_init=False))
            else:
                super().__setitem__(parameter, default_type())

    def import_args(self, args: dict) -> None:
        """ Imports data from an argument dict. """
        for arg, value in args.items():
            self.logger.info("Importing argument '%s' with value: %s" % (arg, value))
            self[arg] = value

    def __setitem__(self, key: str, value) -> None:
        # If the type is registered, use the appropriate update function
        if expected_type := self.builtin_parameters.get(key, self['custom_parameters'].get(key)):
            self.logger.log(5, "[%s] Expected type: %s" % (key, expected_type))
            if hasattr(self, f"_process_{key}"):
                self.logger.log(5, "[%s] Using builtin setitem: %s" % (key, f"_process_{key}"))
                getattr(self, f"_process_{key}")(value)
            elif func := self['custom_processing'].get(f"_process_{key}"):
                self.logger.log(5, "[%s] Using custom setitem: %s" % (key, func.__name__))
                func(self, value)
            elif func := self['custom_processing'].get(f"_process_{key}_multi"):
                self.logger.log(5, "[%s] Using custom plural setitem: %s" % (key, func.__name__))
                handle_plural(func)(self, value)
            elif expected_type in (list, NoDupFlatList):
                self.logger.log(5, "Using list setitem for: %s" % key)
                self[key].append(value)
            elif expected_type == dict:
                if key not in self:
                    self.logger.log(5, "Setting dict '%s' to: %s" % (key, value))
                    super().__setitem__(key, value)
                else:
                    self.logger.log(5, "Updating dict '%s' with: %s" % (key, value))
                    self[key].update(value)
            else:
                super().__setitem__(key, expected_type(value))
        else:
            self.logger.debug("[%s] Unable to determine expected type, valid builtin types: %s" % (key, self.builtin_parameters.keys()))
            self.logger.debug("[%s] Custom types: %s" % (key, self['custom_parameters'].keys()))
            # for anything but the logger, add to the processing queue
            if key != 'logger':
                self.logger.debug("Adding unknown internal parameter to processing queue: %s" % key)
                if key not in self['_processing']:
                    self['_processing'][key] = Queue()
                self['_processing'][key].put(value)

    @handle_plural
    def _process_custom_parameters(self, parameter_name: str, parameter_type: type) -> None:
        """
        Updates the custom_parameters attribute.
        Sets the initial value of the parameter based on the type.

        If the parameter is in the processing queue, process the queued values.
        """
        self['custom_parameters'][parameter_name] = eval(parameter_type)
        self.logger.debug("Registered custom parameter '%s' with type: %s" % (parameter_name, parameter_type))

        if parameter_type == "NoDupFlatList":
            super().__setitem__(parameter_name, NoDupFlatList(no_warn=True, log_bump=5, logger=self.logger, _log_init=False))
        elif parameter_type in ("list", "dict"):
            super().__setitem__(parameter_name, eval(parameter_type)())
        elif parameter_type == "bool":
            super().__setitem__(parameter_name, False)
        elif parameter_type == "int":
            super().__setitem__(parameter_name, 0)
        elif parameter_type == "float":
            super().__setitem__(parameter_name, 0.0)
        else:
            self.logger.debug("Leaving '%s' as None" % parameter_name)

        if parameter_name in self['_processing']:
            self.logger.debug("Processing queued values for '%s'" % parameter_name)
            while not self['_processing'][parameter_name].empty():
                value = self['_processing'][parameter_name].get()
                if self['validated']:
                    self.logger.info("Processing queued value for '%s': %s" % (parameter_name, value))
                else:
                    self.logger.debug("Processing queued value for '%s': %s" % (parameter_name, value))
                self[parameter_name] = value
            self['_processing'].pop(parameter_name)

    @handle_plural
    def _process_imports(self, import_type: str, import_value: dict) -> None:
        """ Processes imports in a module, importing the functions and adding them to the appropriate list. """
        from importlib import import_module
        from importlib.util import spec_from_file_location, module_from_spec

        self.logger.debug("Processing imports of type: %s" % import_type)

        for module_name, function_names in import_value.items():
            self.logger.debug("Importing module: %s" % module_name)

            try:
                module = import_module(module_name)
            except ModuleNotFoundError as e:
                module_path = Path('/var/lib/ugrd/' + module_name.replace('.', '/')).with_suffix('.py')
                self.logger.debug("Attempting to sideload module from: %s" % module_path)
                if not module_path.exists():
                    raise ModuleNotFoundError("Module not found: %s" % module_name) from e
                try:
                    spec = spec_from_file_location(module_name, module_path)
                    module = module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception as e:
                    raise ModuleNotFoundError("Unable to load module: %s" % module_name) from e

            self.logger.log(5, "[%s] Imported module contents: %s" % (module_name, dir(module)))
            if '_module_name' in dir(module) and module._module_name != module_name:
                self.logger.warning("Module name mismatch: %s != %s" % (module._module_name, module_name))

            function_list = [getattr(module, function_name) for function_name in function_names]

            if import_type not in self['imports']:
                self.logger.log(5, "Creating import type: %s" % import_type)
                self['imports'][import_type] = NoDupFlatList(log_bump=10, logger=self.logger, _log_init=False)

            if import_type == 'custom_init':
                if self['imports']['custom_init']:
                    raise ValueError("Custom init function already defined: %s" % self['imports']['custom_init'])
                else:
                    self['imports']['custom_init'] = function_list[0]
                    self.logger.info("Registered custom init function: %s" % function_list[0].__name__)
                    continue

            if import_type == 'funcs':
                for function in function_list:
                    if function.__name__ in self['imports']['funcs']:
                        raise ValueError("Function '%s' already registered" % function.__name__)
                    if function.__name__ in self['binaries']:
                        raise ValueError("Function collides with defined binary: %s'" % function.__name__)

            self['imports'][import_type] += function_list
            self.logger.debug("[%s] Updated import functions: %s" % (import_type, function_list))

            if import_type == 'config_processing':
                for function in function_list:
                    self['custom_processing'][function.__name__] = function
                    self.logger.debug("Registered config processing function: %s" % function.__name__)

    @handle_plural
    def _process_modules(self, module: str) -> None:
        """
        processes a single module into the config
        takes list with decorator
        """
        if module in self['modules']:
            self.logger.debug("Module '%s' already loaded" % module)
            return

        self.logger.info("Processing module: %s" % module)

        module_subpath = module.replace('.', '/') + '.toml'

        module_path = Path(__file__).parent.parent / module_subpath
        if not module_path.exists():
            module_path = Path('/var/lib/ugrd') / module_subpath
            if not module_path.exists():
                raise FileNotFoundError("Unable to locate module: %s" % module)
        self.logger.debug("Module path: %s" % module_path)

        with open(module_path, 'rb') as module_file:
            try:
                module_config = load(module_file)
            except TOMLDecodeError as e:
                raise TOMLDecodeError("Unable to load module config: %s" % module) from e

        # First import all variabled, then import processing functions/imports in order
        processing_imports = ['imports', 'custom_parameters']
        for name, value in module_config.items():
            if name in processing_imports:
                self.logger.log(5, "[%s] Skipping '%s'" % (module, name))
                continue
            self.logger.debug("[%s] Setting '%s' to: %s" % (module, name, value))
            self[name] = value

        for import_type in processing_imports:
            if import_type in module_config:
                self[import_type] = module_config[import_type]
                self.logger.debug("[%s] Registered %s: %s" % (module, import_type, self[import_type]))

        # Append the module to the list of loaded modules, avoid recursion
        self['modules'].append(module)

    def verify_mask(self) -> None:
        """ Processes masked imports. """
        for mask_hook, mask_items in self['masks'].items():
            if runlevel := self['imports'].get(mask_hook):
                for function in runlevel.copy():
                    if function.__name__ in mask_items:
                        runlevel.remove(function)
                        self.logger.warning("[%s] Masking import: %s" % (mask_hook, function.__name__))

    def validate(self) -> None:
        """ Validate config """
        if self['_processing']:
            self.logger.critical("Unprocessed config values: %s" % ', '.join(list(self['_processing'].keys())))
        self.verify_mask()
        self['validated'] = True

    def __str__(self) -> str:
        return pretty_print(self)
