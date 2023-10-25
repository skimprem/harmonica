# Copyright (c) 2018 The Harmonica Developers.
# Distributed under the terms of the BSD 3-Clause License.
# SPDX-License-Identifier: BSD-3-Clause
#
# This code is part of the Fatiando a Terra project (https://www.fatiando.org)
#
"""
Compute magnetic field generated by rectangular prisms
"""
import numpy as np
from choclo.prism import magnetic_e, magnetic_field, magnetic_n, magnetic_u
from numba import jit, prange

from .prism_gravity import _check_prisms
from .utils import initialize_progressbar


def prism_magnetic(
    coordinates,
    prisms,
    magnetization,
    parallel=True,
    dtype=np.float64,
    progressbar=False,
    disable_checks=False,
):
    """
    Magnetic field of right-rectangular prisms in Cartesian coordinates

    Parameters
    ----------
    coordinates : list of arrays
        List of arrays containing the ``easting``, ``northing`` and ``upward``
        coordinates of the computation points defined on a Cartesian coordinate
        system. All coordinates should be in meters.
    prisms : list, 1d-array, or 2d-array
        List or array containing the coordinates of the prism(s) in the
        following order:
        west, east, south, north, bottom, top in a Cartesian coordinate system.
        All coordinates should be in meters. Coordinates for more than one
        prism can be provided. In this case, *prisms* should be a list of lists
        or 2d-array (with one prism per row).
    magnetization : list or array
        List or array containing the magnetization vector of each prism in
        :math:`Am^{-1}`. Each vector should be an array with three elements
        in the following order: ``magnetization_e``, ``magnetization_n``,
        ``magnetization_u``.
    parallel : bool (optional)
        If True the computations will run in parallel using Numba built-in
        parallelization. If False, the forward model will run on a single core.
        Might be useful to disable parallelization if the forward model is run
        by an already parallelized workflow. Default to True.
    dtype : data-type (optional)
        Data type assigned to the resulting gravitational field. Default to
        ``np.float64``.
    progressbar : bool (optional)
        If True, a progress bar of the computation will be printed to standard
        error (stderr). Requires :mod:`numba_progress` to be installed.
        Default to ``False``.
    disable_checks : bool (optional)
        Flag that controls whether to perform a sanity check on the model.
        Should be set to ``True`` only when it is certain that the input model
        is valid and it does not need to be checked.
        Default to ``False``.

    Returns
    -------
    magnetic_field : tuple of array
        Tuple containing each component of the magnetic field generated by the
        prisms as arrays. The three components are returned in the following
        order: ``b_e``, ``b_n``, ``b_u``.
    """
    # Figure out the shape and size of the output array(s)
    cast = np.broadcast(*coordinates[:3])
    # Convert coordinates, prisms and magnetization to arrays with proper shape
    coordinates = tuple(np.atleast_1d(i).ravel() for i in coordinates[:3])
    prisms = np.atleast_2d(prisms)
    magnetization = np.atleast_2d(magnetization)
    # Sanity checks
    if not disable_checks:
        _run_sanity_checks(prisms, magnetization)
    # Discard null prisms (zero volume or null magnetization)
    prisms, magnetization = _discard_null_prisms(prisms, magnetization)
    # Run computations
    b_e, b_n, b_u = tuple(np.zeros(cast.size, dtype=dtype) for _ in range(3))
    with initialize_progressbar(coordinates[0].size, progressbar) as progress_proxy:
        if parallel:
            _jit_prism_magnetic_field_parallel(
                coordinates, prisms, magnetization, b_e, b_n, b_u, progress_proxy
            )
        else:
            _jit_prism_magnetic_field_serial(
                coordinates, prisms, magnetization, b_e, b_n, b_u, progress_proxy
            )
    # Convert to nT
    b_e *= 1e9
    b_n *= 1e9
    b_u *= 1e9
    return b_e.reshape(cast.shape), b_n.reshape(cast.shape), b_u.reshape(cast.shape)


def prism_magnetic_component(
    coordinates,
    prisms,
    magnetization,
    component,
    parallel=True,
    dtype=np.float64,
    progressbar=False,
    disable_checks=False,
):
    """
    Compute single component of the magnetic field of right-rectangular prisms

    .. important::

        Use this function only if you need to compute a single component of the
        magnetic field. Use :func:`harmonica.prism_magnetic` to compute the
        three components more efficiently.

    Parameters
    ----------
    coordinates : list or 1d-array
        List or array containing ``easting``, ``northing`` and ``upward`` of
        the computation points defined on a Cartesian coordinate system.
        All coordinates should be in meters.
    prisms : list, 1d-array, or 2d-array
        List or array containing the coordinates of the prism(s) in the
        following order:
        west, east, south, north, bottom, top in a Cartesian coordinate system.
        All coordinates should be in meters. Coordinates for more than one
        prism can be provided. In this case, *prisms* should be a list of lists
        or 2d-array (with one prism per line).
    magnetization : list or array
        List or array containing the magnetization vector of each prism in
        :math:`Am^{-1}`. Each vector should be an array with three elements
        in the following order: ``magnetization_e``, ``magnetization_n``,
        ``magnetization_u``.
    component : str
        Computed that will be computed. Available options are: ``"easting"``,
        ``"northing"`` or ``"upward"``.
    parallel : bool (optional)
        If True the computations will run in parallel using Numba built-in
        parallelization. If False, the forward model will run on a single core.
        Might be useful to disable parallelization if the forward model is run
        by an already parallelized workflow. Default to True.
    dtype : data-type (optional)
        Data type assigned to the resulting gravitational field. Default to
        ``np.float64``.
    progressbar : bool (optional)
        If True, a progress bar of the computation will be printed to standard
        error (stderr). Requires :mod:`numba_progress` to be installed.
        Default to ``False``.
    disable_checks : bool (optional)
        Flag that controls whether to perform a sanity check on the model.
        Should be set to ``True`` only when it is certain that the input model
        is valid and it does not need to be checked.
        Default to ``False``.

    Returns
    -------
    b_component : array
        Array with the component of the magnetic field generated by the
        prisms on every observation point.
    """
    # Figure out the shape and size of the output array(s)
    cast = np.broadcast(*coordinates[:3])
    # Convert coordinates, prisms and magnetization to arrays with proper shape
    coordinates = tuple(np.atleast_1d(i).ravel() for i in coordinates[:3])
    prisms = np.atleast_2d(prisms)
    magnetization = np.atleast_2d(magnetization)
    # Choose forward modelling function based on the chosen component
    forward_function = _get_magnetic_forward_function(component)
    # Sanity checks
    if not disable_checks:
        _run_sanity_checks(prisms, magnetization)
    # Discard null prisms (zero volume or null magnetization)
    prisms, magnetization = _discard_null_prisms(prisms, magnetization)
    # Run computations
    result = np.zeros(cast.size, dtype=dtype)
    with initialize_progressbar(coordinates[0].size, progressbar) as progress_proxy:
        if parallel:
            _jit_prism_magnetic_component_parallel(
                coordinates,
                prisms,
                magnetization,
                result,
                forward_function,
                progress_proxy,
            )
        else:
            _jit_prism_magnetic_component_serial(
                coordinates,
                prisms,
                magnetization,
                result,
                forward_function,
                progress_proxy,
            )
    # Convert to nT
    result *= 1e9
    return result.reshape(cast.shape)


def _jit_prism_magnetic_field(
    coordinates, prisms, magnetization, b_e, b_n, b_u, progress_proxy=None
):
    """
    Compute magnetic fields of prisms on computation points

    Parameters
    ----------
    coordinates : tuple
        Tuple containing ``easting``, ``northing`` and ``upward`` of the
        computation points as arrays, all defined on a Cartesian coordinate
        system and in meters.
    prisms : 2d-array
        Two dimensional array containing the coordinates of the prism(s) in the
        following order: west, east, south, north, bottom, top in a Cartesian
        coordinate system.
        All coordinates should be in meters.
    magnetization : 2d-array
        Array containing the magnetization vector of each prism in
        :math:`Am^{-1}`. Each vector will be a row in the 2d-array.
    b_e : 1d-array
        Array where the resulting values of the easting component of the
        magnetic field will be stored.
    b_n : 1d-array
        Array where the resulting values of the northing component of the
        magnetic field will be stored.
    b_u : 1d-array
        Array where the resulting values of the upward component of the
        magnetic field will be stored.
    progress_proxy : :class:`numba_progress.ProgressBar` or None
        Instance of :class:`numba_progress.ProgressBar` that gets updated after
        each iteration on the observation points. Use None if no progress bar
        is should be used.
    """
    # Check if we need to update the progressbar on each iteration
    update_progressbar = progress_proxy is not None
    # Iterate over computation points and prisms
    for l in prange(coordinates[0].size):
        for m in range(prisms.shape[0]):
            easting_comp, northing_comp, upward_comp = magnetic_field(
                coordinates[0][l],
                coordinates[1][l],
                coordinates[2][l],
                prisms[m, 0],
                prisms[m, 1],
                prisms[m, 2],
                prisms[m, 3],
                prisms[m, 4],
                prisms[m, 5],
                magnetization[m, 0],
                magnetization[m, 1],
                magnetization[m, 2],
            )
            b_e[l] += easting_comp
            b_n[l] += northing_comp
            b_u[l] += upward_comp
        # Update progress bar if called
        if update_progressbar:
            progress_proxy.update(1)


def _jit_prism_magnetic_component(
    coordinates, prisms, magnetization, result, forward_function, progress_proxy=None
):
    """
    Compute a single component of the magnetic field of prisms

    Parameters
    ----------
    coordinates : tuple
        Tuple containing ``easting``, ``northing`` and ``upward`` of the
        computation points as arrays, all defined on a Cartesian coordinate
        system and in meters.
    prisms : 2d-array
        Two dimensional array containing the coordinates of the prism(s) in the
        following order: west, east, south, north, bottom, top in a Cartesian
        coordinate system.
        All coordinates should be in meters.
    magnetization : 2d-array
        Array containing the magnetization vector of each prism in
        :math:`Am^{-1}`. Each vector will be a row in the 2d-array.
    result : 1d-array
        Array where the resulting values of the desired component of the
        magnetic field will be stored.
    forward_function : callable
        Forward function to be used to compute the desired component of the
        magnetic field. Choose one of :func:`choclo.prism.magnetic_easting`,
        :func:`choclo.prism.magnetic_northing` or
        :func:`choclo.prism.magnetic_upward`.
    progress_proxy : :class:`numba_progress.ProgressBar` or None
        Instance of :class:`numba_progress.ProgressBar` that gets updated after
        each iteration on the observation points. Use None if no progress bar
        is should be used.
    """
    # Check if we need to update the progressbar on each iteration
    update_progressbar = progress_proxy is not None
    # Iterate over computation points and prisms
    for l in prange(coordinates[0].size):
        for m in range(prisms.shape[0]):
            result[l] += forward_function(
                coordinates[0][l],
                coordinates[1][l],
                coordinates[2][l],
                prisms[m, 0],
                prisms[m, 1],
                prisms[m, 2],
                prisms[m, 3],
                prisms[m, 4],
                prisms[m, 5],
                magnetization[m, 0],
                magnetization[m, 1],
                magnetization[m, 2],
            )
        # Update progress bar if called
        if update_progressbar:
            progress_proxy.update(1)


def _discard_null_prisms(prisms, magnetization):
    """
    Discard prisms with zero volume or null magnetization

    Parameters
    ----------
    prisms : 2d-array
        Array containing the boundaries of the prisms in the following order:
        ``w``, ``e``, ``s``, ``n``, ``bottom``, ``top``.
        The array must have the following shape: (``n_prisms``, 6), where
        ``n_prisms`` is the total number of prisms.
        This array of prisms must have valid boundaries.
        Run ``_check_prisms`` before.
    magnetization : 2d-array
        Array containing the magnetization vector of each prism in
        :math:`Am^{-1}`. Each vector will be a row in the 2d-array.

    Returns
    -------
    prisms : 2d-array
        A copy of the ``prisms`` array that doesn't include the null prisms
        (prisms with zero volume or zero density).
    magnetization : 2d-array
        A copy of the ``magnetization`` array that doesn't include the
        magnetization vectors for null prisms (prisms with zero volume or
        null magnetization).
    """
    west, east, south, north, bottom, top = tuple(prisms[:, i] for i in range(6))
    # Mark prisms with zero volume as null prisms
    null_prisms = (west == east) | (south == north) | (bottom == top)
    # Mark prisms with null magnetization as null prisms
    null_prisms[(magnetization == 0).all(axis=1)] = True
    # Keep only non null prisms
    prisms = prisms[np.logical_not(null_prisms), :]
    magnetization = magnetization[np.logical_not(null_prisms)]
    return prisms, magnetization


def _run_sanity_checks(prisms, magnetization):
    """
    Run sanity checks on prisms and their magnetization
    """
    if magnetization.shape[0] != prisms.shape[0]:
        raise ValueError(
            f"Number of magnetization vectors ({magnetization.shape[0]}) "
            + f"mismatch the number of prisms ({prisms.shape[0]})"
        )
    if magnetization.shape[1] != 3:
        raise ValueError(
            f"Found magnetization vectors with '{magnetization.shape[1]}' "
            + "elements. Magnetization vectors should have only 3 elements."
        )
    _check_prisms(prisms)


def _get_magnetic_forward_function(component):
    """
    Returns the Choclo magnetic forward modelling function for the desired
    component

    Parameters
    ----------
    component : str
        Magnetic field component.

    Returns
    -------
    forward_function : callable
        Forward modelling function for the desired component.
    """
    if component not in ("easting", "northing", "upward"):
        raise ValueError(
            f"Invalid component '{component}'. "
            "It must be either 'easting', 'northing' or 'upward'."
        )
    functions = {"easting": magnetic_e, "northing": magnetic_n, "upward": magnetic_u}
    return functions[component]


# Define jitted versions of the forward modelling function
_jit_prism_magnetic_field_serial = jit(nopython=True)(_jit_prism_magnetic_field)
_jit_prism_magnetic_field_parallel = jit(nopython=True, parallel=True)(
    _jit_prism_magnetic_field
)
_jit_prism_magnetic_component_serial = jit(nopython=True)(_jit_prism_magnetic_component)
_jit_prism_magnetic_component_parallel = jit(nopython=True, parallel=True)(
    _jit_prism_magnetic_component
)