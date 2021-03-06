import json
import numpy as np
from mpi4py import MPI

class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(
                *args, **kwargs)
        return cls._instances[cls]


class NumpyEncoder(json.JSONEncoder):
    """Numpy helper for json."""
    # pylint: disable=method-hidden,arguments-differ
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


class Logger(metaclass=Singleton):
    """Logger for timestepping scheme."""
    def __init__(self, ofreq=10):
        """
        Arguments:
        output -- output filename
        ofreq  -- save every ofreq steps (Default: 10)
        """
        self.active = False
        self.current = {}
        self.log = []
        self.output = 'md_results.json'
        self.ofreq = ofreq

    @property
    def ofreq(self):
        return self._ofreq

    @ofreq.setter
    def ofreq(self, ofreq):
        self._ofreq = ofreq

    @property
    def output(self):
        return self._output

    @output.setter
    def output(self, output):
        self._output = output

    def __enter__(self):
        self.log = []
        self.active = True

    def __exit__(self, cls, value, traceback):
        if not MPI.COMM_WORLD.rank == 0:
            return

        self.active = False
        if len(self.current) > 0:
            self.log.append(self.current)
            self.current = {}
        with open(self.output, 'w') as fh:
            json.dump(self.log, fh, cls=NumpyEncoder)

    def insert(self, entries):
        """insert entries (dict)"""
        if not self.active:
            return

        if set(entries) < set(self.current):
            self.log.append(self.current)
            self.current = {}

        if self.ofreq is not None and len(self.current) % self.ofreq == 0:
            if MPI.COMM_WORLD.rank == 0:
                with open(self.output, 'w') as fh:
                    json.dump(self.log, fh, cls=NumpyEncoder)

        self.current = {**self.current, **entries}
