import json
import yaml
import matplotlib.pyplot as plt
import numpy as np
import argparse
from sirius import (DFT_ground_state_find, atom_positions,
                    initialize_subspace,
                    set_atom_positions)
from sirius import Logger as pprinter

from .atom_mass import atom_masses
from .dft_ground_state import make_dft
from .logger import Logger
import time

pprint = pprinter()

def initialize(tol=None):
    """Initialize DFT_ground_state object."""
    sirius_config = json.load(open('sirius.json', 'r'))
    if tol is not None:
        sirius_config['parameters']['potential_tol'] = tol
        sirius_config['parameters']['energy_tol'] = tol
    else:
        sirius_config['parameters']['potential_tol'] = 1e-10
        sirius_config['parameters']['energy_tol'] = 1e-10

    res = DFT_ground_state_find(num_dft_iter=3, config=sirius_config)

    return res["kpointset"], res["density"], res["potential"], res["dft_gs"]


class ScfConvergenceError(Exception):
    """Custom exception."""


class Force:
    """Compute forces. """

    def __init__(self, dft):
        self.dft = dft
        self.unit_cell = dft.dft_obj.k_point_set().ctx().unit_cell()
        self.L = self.unit_cell.lattice_vectors()
        self.Lh = np.linalg.inv(self.L)

    def __call__(self, pos):
        """Computes ground state for updated positions and returns total energy and forces.
        Hint: no extrapolation is done
        Arguments:
        - pos Atom poitions in reduced coordinates

        Returns:
        - forces (in reduced coordinates)
        - Etot
        """
        # apply periodic boundary conditions
        res = self.dft.update_and_find(pos)
        if not res['converged']:
            raise ScfConvergenceError('failed to converge')
        Logger().insert({'nscf': res['num_scf_iterations'],
                         'band_gap': res['band_gap'],
                         'scf_dict': res})
        pprint('band_gap: ', res['band_gap'])
        forces = np.array(self.dft.dft_obj.forces().calc_forces_total()).T
        pprint('nscf: ', res['num_scf_iterations'])

        Logger().insert({
            'forces': {
                'ewald': np.array(self.dft.dft_obj.forces().ewald),
                'vloc': np.array(self.dft.dft_obj.forces().vloc),
                'nonloc': np.array(self.dft.dft_obj.forces().nonloc),
                'core': np.array(self.dft.dft_obj.forces().core),
                'scf_corr': np.array(self.dft.dft_obj.forces().scf_corr)
            }
        })
        # convert forces to reduced coordinates
        return forces@self.Lh.T, res['energy']['total']


def velocity_verlet(x, v, F, dt, Fh, m):
    """Velocity Verlet.
    Arguments:
    x  -- atom positions in reduced coordinates
    v  -- velocity
    F  -- forces
    dt -- time step
    Fh -- handle to compute force, e.g Fh(x)
    m  -- atomic masses

    Returns:
    x -- atom positions
    v -- velocities
    F -- forces
    E -- Kohn-Sham energy
    """
    m = m[:, np.newaxis]  # enable broadcasting in numpy
    # update positions
    xn = x + v * dt + 0.5 * F / m * dt ** 2
    t1 = time.time()
    Fn, EKS = Fh(xn)
    gs_json = Fh.dft.dft_obj.serialize()
    # atomic moments
    mm = np.array(Fh.dft.dft_obj.E.density.compute_atomic_mag_mom()).T

    t2 = time.time()
    vn = v + 0.5 / m * (F + Fn) * dt
    # remove momentum
    p = np.sum(vn * m, axis=0)
    pprint('momentum:', p)
    # vn -= p / np.sum(m)
    # pprint('momentum (fixed):', p)
    Logger().insert({'t_evalforce': t2-t1,
                     'momentum': p,
                     'energy_components': gs_json['energy'],
                     'atomic_mag_mom': mm,
                     'F': Fn})

    return xn, vn, Fn, EKS


def to_cart(x, L):
    assert L.shape == (3, 3)
    return x@L.T


def from_cart(x, L):
    assert L.shape == (3, 3)
    return x@np.linalg.inv(L).T


def run():
    input_vars = yaml.load(open('input.yml', 'r'))
    N = input_vars['parameters']['N']
    dt = input_vars['parameters']['dt']

    kset, _, _, dft_ = initialize(input_vars['parameters']['energy_tol'])

    dft = make_dft(dft_, input_vars)

    unit_cell = kset.ctx().unit_cell()
    lattice_vectors = np.array(unit_cell.lattice_vectors())

    Fh = Force(dft)

    x0 = atom_positions(unit_cell)
    F, EKS = Fh(x0)
    v0 = np.zeros_like(x0)
    na = len(x0)  # number of atoms
    atom_types = [unit_cell.atom(i).label for i in range(na)]
    # masses in A_r
    m = np.array([atom_masses[label] for label in atom_types])

    with Logger():
        # Velocity Verlet time-stepping
        for i in range(N):
            pprint('iteration: ', i, '\n')

            xn, vn, Fn, EKS = velocity_verlet(x0, v0, F, dt, Fh, m)
            pprint("displacement: %.2e" % np.linalg.norm(xn - x0))
            vc = to_cart(vn, lattice_vectors)
            ekin = 0.5 * np.sum(vc**2 * m[:, np.newaxis])
            pprint("Etot: %10.8f, Ekin: %10.8f, Eks: %10.8f" % (EKS + ekin, ekin, EKS))
            Logger().insert(
                {"i": i,
                 "v": to_cart(vn, lattice_vectors),
                 "x": to_cart(xn, lattice_vectors),
                 "E": EKS + ekin, "EKS": EKS, "ekin": ekin, 't': i*dt}
            )
            x0 = xn
            v0 = vn
            F = Fn


if __name__ == '__main__':
    run()
