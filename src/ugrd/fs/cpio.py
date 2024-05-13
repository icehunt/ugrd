__author__ = 'desultory'
__version__ = '2.7.1'


from pycpio import PyCPIO


def check_cpio(self, cpio: PyCPIO) -> None:
    """ Checks that all dependenceis are in the generated CPIO file. """
    for dep in self['dependencies']:
        if str(dep) not in cpio.entries:
            raise FileNotFoundError("Dependency not found in CPIO: %s" % dep)
        else:
            self.logger.debug("Dependency found in CPIO: %s" % dep)


def make_cpio(self) -> None:
    """
    Creates a CPIO archive from the build directory and writes it to the output directory.
    Raises FileNotFoundError if the output directory does not exist.
    """
    cpio = PyCPIO(logger=self.logger, _log_bump=10)
    cpio.append_recursive(self.build_dir, relative=True)
    check_cpio(self, cpio)

    if self.get('mknod_cpio'):
        for node in self['nodes'].values():
            self.logger.debug("Adding CPIO node: %s" % node)
            cpio.add_chardev(name=node['path'], mode=node['mode'], major=node['major'], minor=node['minor'])

    out_cpio = self.out_dir / self.out_file

    if not out_cpio.parent.exists():
        self._mkdir(out_cpio.parent)

    if out_cpio.exists():
        self._rotate_old(out_cpio)

    cpio.write_cpio_file(out_cpio, _log_bump=-10, _log_init=False)


def _process_out_file(self, out_file):
    """ Processes the out_file configuration option. """
    from pathlib import Path
    if Path(out_file).is_dir():
        self.logger.info("Specified out_file is a directory, setting out_dir: %s" % out_file)
        self['out_dir'] = out_file
        return

    if out_file.startswith('./'):
        from pathlib import Path
        self.logger.debug("Relative out_file path detected: %s" % out_file)
        self['out_dir'] = Path('.').resolve()
        self.logger.info("Resolved out_dir to: %s" % self['out_dir'])
        out_file = Path(out_file[2:])

    dict.__setitem__(self, 'out_file', out_file)
