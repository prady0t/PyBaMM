#
# Tests for the KLU-Jax interface class
#
from tests import TestCase
from parameterized import parameterized

import pybamm
import numpy as np
import unittest

testcase = []
if pybamm.have_idaklu() and pybamm.have_jax():
    from jax.tree_util import tree_flatten
    import jax
    import jax.numpy as jnp

    inputs = {
        "Current function [A]": 0.222,
        "Separator porosity": 0.3,
    }

    model = pybamm.lithium_ion.DFN()
    geometry = model.default_geometry
    param = model.default_parameter_values
    param.update({key: "[input]" for key in inputs.keys()})
    param.process_geometry(geometry)
    param.process_model(model)
    var = pybamm.standard_spatial_vars
    var_pts = {var.x_n: 20, var.x_s: 20, var.x_p: 20, var.r_n: 10, var.r_p: 10}
    mesh = pybamm.Mesh(geometry, model.default_submesh_types, var_pts)
    disc = pybamm.Discretisation(mesh, model.default_spatial_methods)
    disc.process_model(model)
    t_eval = np.linspace(0, 360, 10)
    idaklu_solver = pybamm.IDAKLUSolver(rtol=1e-6, atol=1e-6)

    # Create surrogate data (using base IDAKLU solver)
    sim = idaklu_solver.solve(
        model,
        t_eval,
        inputs=inputs,
        calculate_sensitivities=True,
    )

    # Get jax expressions for IDAKLU solver
    output_variables = [
        "Voltage [V]",
        "Current [A]",
        "Time [min]",
    ]
    # Single output variable
    idaklu_jax_solver1 = idaklu_solver.jaxify(
        model,
        t_eval,
        output_variables=output_variables[:1],
        inputs=inputs,
        calculate_sensitivities=True,
    )
    f1 = idaklu_jax_solver1.get_jaxpr()
    # Multiple output variables
    idaklu_jax_solver3 = idaklu_solver.jaxify(
        model,
        t_eval,
        output_variables=output_variables,
        inputs=inputs,
        calculate_sensitivities=True,
    )
    f3 = idaklu_jax_solver3.get_jaxpr()

    # Common test parameters

    in_axes = (0, None)  # vmap over time, not inputs
    k = 5  # time index for scalar tests

    # Define passthrough wrapper for non-jitted evaluation
    def no_jit(f):
        return f

    testcase = [
        (output_variables[:1], idaklu_jax_solver1, f1, no_jit),  # single output
        (output_variables[:1], idaklu_jax_solver1, f1, jax.jit),  # jit single output
        (output_variables, idaklu_jax_solver3, f3, no_jit),  # multiple outputs
        (output_variables, idaklu_jax_solver3, f3, jax.jit),  # jit multiple outputs
    ]


@unittest.skipIf(
    not pybamm.have_idaklu() or not pybamm.have_jax(),
    "IDAKLU Solver and/or JAX are not available",
)
class TestIDAKLUJax(TestCase):
    # Initialisation tests

    def test_initialise_twice(self):
        idaklu_jax_solver = idaklu_solver.jaxify(
            model,
            t_eval,
            output_variables=output_variables,
            inputs=inputs,
            calculate_sensitivities=True,
        )
        with self.assertWarns(UserWarning):
            idaklu_jax_solver.jaxify(
                model,
                t_eval,
                output_variables=output_variables,
                inputs=inputs,
                calculate_sensitivities=True,
            )

    def test_uninitialised(self):
        idaklu_jax_solver = pybamm.IDAKLUJax(idaklu_solver)
        with self.assertRaises(pybamm.SolverError):
            idaklu_jax_solver.get_jaxpr()
        with self.assertRaises(pybamm.SolverError):
            idaklu_jax_solver.jax_value()
        with self.assertRaises(pybamm.SolverError):
            idaklu_jax_solver.jax_grad()

    def test_no_output_variables(self):
        with self.assertRaises(pybamm.SolverError):
            idaklu_solver.jaxify(
                model,
                t_eval,
                inputs=inputs,
            )

    def test_no_inputs(self):
        # Regenerate model with no inputs
        model = pybamm.lithium_ion.DFN()
        geometry = model.default_geometry
        param = model.default_parameter_values
        param.process_geometry(geometry)
        param.process_model(model)
        var = pybamm.standard_spatial_vars
        var_pts = {var.x_n: 20, var.x_s: 20, var.x_p: 20, var.r_n: 10, var.r_p: 10}
        mesh = pybamm.Mesh(geometry, model.default_submesh_types, var_pts)
        disc = pybamm.Discretisation(mesh, model.default_spatial_methods)
        disc.process_model(model)
        t_eval = np.linspace(0, 360, 10)
        idaklu_solver = pybamm.IDAKLUSolver(rtol=1e-6, atol=1e-6)
        # Regenerate surrogate data
        sim = idaklu_solver.solve(model, t_eval)
        idaklu_jax_solver = idaklu_solver.jaxify(
            model,
            t_eval,
            output_variables=output_variables,
        )
        f = idaklu_jax_solver.get_jaxpr()
        # Check that evaluation can occur (and is correct) with no inputs
        out = f(t_eval)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval) for outvar in output_variables]).T
        )

    # Scalar evaluation

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_f_scalar(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(f)(t_eval[k], inputs)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval[k]) for outvar in output_variables]).T
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_f_vector(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(f)(t_eval, inputs)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval) for outvar in output_variables]).T
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_f_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(jax.vmap(f, in_axes=in_axes))(t_eval, inputs)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval) for outvar in output_variables]).T
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_f_batch_over_inputs(self, output_variables, idaklu_jax_solver, f, wrapper):
        inputs_mock = np.array([1.0, 2.0, 3.0])
        with self.assertRaises(NotImplementedError):
            wrapper(jax.vmap(f, in_axes=(None, 0)))(t_eval, inputs_mock)

    # Get all vars (should mirror test_f_* [above])

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvars_scalar(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(idaklu_jax_solver.get_vars(f, output_variables))(
            t_eval[k], inputs
        )
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval[k]) for outvar in output_variables]).T
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvars_vector(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(idaklu_jax_solver.get_vars(f, output_variables))(t_eval, inputs)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval) for outvar in output_variables]).T
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvars_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(
            jax.vmap(
                idaklu_jax_solver.get_vars(f, output_variables),
                in_axes=(0, None),
            ),
        )(t_eval, inputs)
        np.testing.assert_allclose(
            out, np.array([sim[outvar](t_eval) for outvar in output_variables]).T
        )

    # Isolate single output variable

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvar_scalar_float(self, output_variables, idaklu_jax_solver, f, wrapper):
        # Per variable checks
        for outvar in output_variables:
            out = wrapper(idaklu_jax_solver.get_var(f, outvar))(
                float(t_eval[k]), inputs
            )
            np.testing.assert_allclose(out, sim[outvar](float(t_eval[k])))

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvar_scalar(self, output_variables, idaklu_jax_solver, f, wrapper):
        # Per variable checks
        for outvar in output_variables:
            out = wrapper(idaklu_jax_solver.get_var(f, outvar))(t_eval[k], inputs)
            np.testing.assert_allclose(out, sim[outvar](t_eval[k]))

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvar_vector(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(idaklu_jax_solver.get_var(f, outvar))(t_eval, inputs)
            np.testing.assert_allclose(out, sim[outvar](t_eval))

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_getvar_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(
                jax.vmap(
                    idaklu_jax_solver.get_var(f, outvar),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)
            np.testing.assert_allclose(out, sim[outvar](t_eval))

    # Differentiation rules (jacfwd)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_scalar(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(jax.jacfwd(f, argnums=1))(t_eval[k], inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.array([f for f in flat_out]).flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar][k]
                for invar in inputs
                for outvar in output_variables
            ]
        ).T
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vector(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(jax.jacfwd(f, argnums=1))(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        (
            np.testing.assert_allclose(flat_out, check.flatten()),
            f"Got: {flat_out}\nExpected: {check}",
        )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(
            jax.vmap(
                jax.jacfwd(f, argnums=1),
                in_axes=(0, None),
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vmap_wrt_time(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        with self.assertRaises(NotImplementedError):
            wrapper(
                jax.vmap(
                    jax.jacfwd(f, argnums=0),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_batch_over_inputs(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        inputs_mock = np.array([1.0, 2.0, 3.0])
        with self.assertRaises(NotImplementedError):
            wrapper(
                jax.vmap(
                    jax.jacfwd(f, argnums=1),
                    in_axes=(None, 0),
                ),
            )(t_eval, inputs_mock)

    # Differentiation rules (jacrev)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_scalar(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(jax.jacrev(f, argnums=1))(t_eval[k], inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.array([f for f in flat_out]).flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar][k]
                for invar in inputs
                for outvar in output_variables
            ]
        ).T
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vector(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(jax.jacrev(f, argnums=1))(t_eval[k], inputs)
        out = wrapper(jax.jacrev(f, argnums=1))(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(
            jax.vmap(
                jax.jacrev(f, argnums=1),
                in_axes=(0, None),
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_batch_over_inputs(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        inputs_mock = np.array([1.0, 2.0, 3.0])
        with self.assertRaises(NotImplementedError):
            wrapper(
                jax.vmap(
                    jax.jacrev(f, argnums=1),
                    in_axes=(None, 0),
                ),
            )(t_eval, inputs_mock)

    # Forward differentiation rules with get_vars (multiple) and get_var (singular)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_scalar_getvars(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        out = wrapper(
            jax.jacfwd(
                idaklu_jax_solver.get_vars(f, output_variables),
                argnums=1,
            ),
        )(t_eval[k], inputs)
        flat_out, _ = tree_flatten(out)
        check = {  # Form dictionary of results from IDAKLU simulation
            invar: np.array(
                [
                    np.array(sim[outvar].sensitivities[invar][k]).squeeze()
                    for outvar in output_variables
                ]
            )
            for invar in inputs
        }
        flat_check, _ = tree_flatten(check)
        np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_scalar_getvar(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        for outvar in output_variables:
            out = wrapper(
                jax.jacfwd(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval[k], inputs)
            flat_out, _ = tree_flatten(out)
            check = {  # Form dictionary of results from IDAKLU simulation
                invar: np.array(sim[outvar].sensitivities[invar][k]).squeeze()
                for invar in inputs
            }
            flat_check, _ = tree_flatten(check)
            np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vector_getvars(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        out = wrapper(
            jax.jacfwd(
                idaklu_jax_solver.get_vars(f, output_variables),
                argnums=1,
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        check = {  # Form dictionary of results from IDAKLU simulation
            invar: np.concatenate(
                [
                    np.array(sim[outvar].sensitivities[invar])
                    for outvar in output_variables
                ],
                axis=1,
            )
            for invar in inputs
        }
        flat_check, _ = tree_flatten(check)
        np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vector_getvar(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        for outvar in output_variables:
            out = wrapper(
                jax.jacfwd(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval, inputs)
            flat_out, _ = tree_flatten(out)
            check = {  # Form dictionary of results from IDAKLU simulation
                invar: np.array(sim[outvar].sensitivities[invar]).flatten()
                for invar in inputs
            }
            flat_check, _ = tree_flatten(check)
            np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vmap_getvars(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(
            jax.vmap(
                jax.jacfwd(idaklu_jax_solver.get_vars(f, output_variables), argnums=1),
                in_axes=(0, None),
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacfwd_vmap_getvar(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(
                jax.vmap(
                    jax.jacfwd(idaklu_jax_solver.get_var(f, outvar), argnums=1),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)
            flat_out, _ = tree_flatten(out)
            check = {  # Form dictionary of results from IDAKLU simulation
                invar: np.array(sim[outvar].sensitivities[invar]).flatten()
                for invar in inputs
            }
            flat_check, _ = tree_flatten(check)
            np.testing.assert_allclose(flat_out, flat_check)

    # Reverse differentiation rules with get_vars (multiple) and get_var (singular)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_scalar_getvars(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        out = wrapper(
            jax.jacrev(
                idaklu_jax_solver.get_vars(f, output_variables),
                argnums=1,
            ),
        )(t_eval[k], inputs)
        flat_out, _ = tree_flatten(out)
        check = {  # Form dictionary of results from IDAKLU simulation
            invar: np.array(
                [
                    np.array(sim[outvar].sensitivities[invar][k]).squeeze()
                    for outvar in output_variables
                ]
            )
            for invar in inputs
        }
        flat_check, _ = tree_flatten(check)
        np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_scalar_getvar(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        for outvar in output_variables:
            out = wrapper(
                jax.jacrev(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval[k], inputs)
            flat_out, _ = tree_flatten(out)
            flat_out = np.array([f for f in flat_out]).flatten()
            check = np.array(
                [sim[outvar].sensitivities[invar][k] for invar in inputs]
            ).T
            (
                np.testing.assert_allclose(flat_out, check.flatten()),
                f"Got: {flat_out}\nExpected: {check}",
            )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vector_getvars(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        out = wrapper(
            jax.jacrev(
                idaklu_jax_solver.get_vars(f, output_variables),
                argnums=1,
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        check = {  # Form dictionary of results from IDAKLU simulation
            invar: np.concatenate(
                [
                    np.array(sim[outvar].sensitivities[invar])
                    for outvar in output_variables
                ],
                axis=1,
            )
            for invar in inputs
        }
        flat_check, _ = tree_flatten(check)
        np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vector_getvar(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        for outvar in output_variables:
            out = wrapper(
                jax.jacrev(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval, inputs)
            flat_out, _ = tree_flatten(out)
            check = {  # Form dictionary of results from IDAKLU simulation
                invar: np.array(sim[outvar].sensitivities[invar]).flatten()
                for invar in inputs
            }
            flat_check, _ = tree_flatten(check)
            np.testing.assert_allclose(flat_out, flat_check)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vmap_getvars(self, output_variables, idaklu_jax_solver, f, wrapper):
        out = wrapper(
            jax.vmap(
                jax.jacrev(idaklu_jax_solver.get_vars(f, output_variables), argnums=1),
                in_axes=(0, None),
            ),
        )(t_eval, inputs)
        flat_out, _ = tree_flatten(out)
        flat_out = np.concatenate(np.array([f for f in flat_out]), 1).T.flatten()
        check = np.array(
            [
                sim[outvar].sensitivities[invar]
                for invar in inputs
                for outvar in output_variables
            ]
        )
        np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jacrev_vmap_getvar(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(
                jax.vmap(
                    jax.jacrev(idaklu_jax_solver.get_var(f, outvar), argnums=1),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)
            flat_out, _ = tree_flatten(out)
            check = {  # Form dictionary of results from IDAKLU simulation
                invar: np.array(sim[outvar].sensitivities[invar]).flatten()
                for invar in inputs
            }
            flat_check, _ = tree_flatten(check)
            np.testing.assert_allclose(flat_out, flat_check)

    # Gradient rule (takes single variable)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_grad_scalar_getvar(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(
                jax.grad(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval[k], inputs)  # output should be a dictionary of inputs
            flat_out, _ = tree_flatten(out)
            flat_out = np.array([f for f in flat_out]).flatten()
            check = np.array([sim[outvar].sensitivities[invar][k] for invar in inputs])
            np.testing.assert_allclose(flat_out, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_grad_vmap_getvar(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            out = wrapper(
                jax.vmap(
                    jax.grad(
                        idaklu_jax_solver.get_var(f, outvar),
                        argnums=1,
                    ),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)
            flat_out, _ = tree_flatten(out)
            flat_out = np.array([f for f in flat_out]).flatten()
            check = np.array([sim[outvar].sensitivities[invar] for invar in inputs])
            np.testing.assert_allclose(flat_out, check.flatten())

    # Value and gradient (takes single variable)

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_value_and_grad_scalar(
        self, output_variables, idaklu_jax_solver, f, wrapper
    ):
        for outvar in output_variables:
            primals, tangents = wrapper(
                jax.value_and_grad(
                    idaklu_jax_solver.get_var(f, outvar),
                    argnums=1,
                ),
            )(t_eval[k], inputs)
            flat_p, _ = tree_flatten(primals)
            flat_p = np.array([f for f in flat_p]).flatten()
            check = np.array(sim[outvar].data[k])
            np.testing.assert_allclose(flat_p, check.flatten())
            flat_t, _ = tree_flatten(tangents)
            flat_t = np.array([f for f in flat_t]).flatten()
            check = np.array([sim[outvar].sensitivities[invar][k] for invar in inputs])
            np.testing.assert_allclose(flat_t, check.flatten())

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_value_and_grad_vmap(self, output_variables, idaklu_jax_solver, f, wrapper):
        for outvar in output_variables:
            primals, tangents = wrapper(
                jax.vmap(
                    jax.value_and_grad(
                        idaklu_jax_solver.get_var(f, outvar),
                        argnums=1,
                    ),
                    in_axes=(0, None),
                ),
            )(t_eval, inputs)
            flat_p, _ = tree_flatten(primals)
            flat_p = np.array([f for f in flat_p]).flatten()
            check = np.array(sim[outvar].data)
            np.testing.assert_allclose(flat_p, check.flatten())
            flat_t, _ = tree_flatten(tangents)
            flat_t = np.array([f for f in flat_t]).flatten()
            check = np.array([sim[outvar].sensitivities[invar] for invar in inputs])
            np.testing.assert_allclose(flat_t, check.flatten())

    # Helper functions - These return values (not jaxexprs) so cannot be JITed

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jax_vars(self, output_variables, idaklu_jax_solver, f, wrapper):
        if wrapper == jax.jit:
            # Skipping test_jax_vars for jax.jit, jit not supported on helper functions
            return
        out = idaklu_jax_solver.jax_value()
        for outvar in output_variables:
            flat_out, _ = tree_flatten(out[outvar])
            flat_out = np.array([f for f in flat_out]).flatten()
            check = np.array(sim[outvar].data)
            (
                np.testing.assert_allclose(flat_out, check.flatten()),
                f"{outvar}: Got: {flat_out}\nExpected: {check}",
            )

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_jax_grad(self, output_variables, idaklu_jax_solver, f, wrapper):
        if wrapper == jax.jit:
            # Skipping test_jax_grad for jax.jit, jit not supported on helper functions
            return
        out = idaklu_jax_solver.jax_grad()
        for outvar in output_variables:
            flat_out, _ = tree_flatten(out[outvar])
            flat_out = np.array([f for f in flat_out]).flatten()
            check = np.array([sim[outvar].sensitivities[invar] for invar in inputs])
            (
                np.testing.assert_allclose(flat_out, check.flatten()),
                f"{outvar}: Got: {flat_out}\nExpected: {check}",
            )

    # Wrap jaxified expression in another function and take the gradient

    @parameterized.expand(testcase, skip_on_empty=True)
    def test_grad_wrapper_sse(self, output_variables, idaklu_jax_solver, f, wrapper):

        # Use surrogate for experimental data
        data = sim["Voltage [V]"](t_eval)

        # Define SSE function
        #
        # Note that although f returns a vector over time, sse() returns a scalar so
        # that it can be passed to grad() directly using time-vector inputs.
        def sse(t, inputs):
            vf = idaklu_jax_solver.get_var(f, "Voltage [V]")
            return jnp.sum((vf(t_eval, inputs) - data) ** 2)

        # Create an imperfect prediction
        inputs_pred = inputs.copy()
        inputs_pred["Current function [A]"] = 0.150
        sim_pred = idaklu_solver.solve(
            model,
            t_eval,
            inputs=inputs_pred,
            calculate_sensitivities=True,
        )
        pred = sim_pred["Voltage [V]"]

        # Check value against actual SSE
        sse_actual = np.sum((pred(t_eval) - data) ** 2)
        flat_out, _ = tree_flatten(sse(t_eval, inputs_pred))
        flat_out = np.array([f for f in flat_out]).flatten()
        flat_check_val, _ = tree_flatten(sse_actual)
        (
            np.testing.assert_allclose(flat_out, flat_check_val, 1e-3),
            f"Got: {flat_out}\nExpected: {flat_check_val}",
        )

        # Check grad against actual
        sse_grad_actual = {}
        for k, v in inputs_pred.items():
            sse_grad_actual[k] = 2 * np.sum(
                (pred(t_eval) - data) * pred.sensitivities[k]
            )
        sse_grad = wrapper(jax.grad(sse, argnums=1))(t_eval, inputs_pred)
        flat_out, _ = tree_flatten(sse_grad)
        flat_out = np.array([f for f in flat_out]).flatten()
        flat_check_grad, _ = tree_flatten(sse_grad_actual)
        (
            np.testing.assert_allclose(flat_out, flat_check_grad, 1e-3),
            f"Got: {flat_out}\nExpected: {flat_check_grad}",
        )

        # Check value_and_grad return
        sse_val, sse_grad = wrapper(jax.value_and_grad(sse, argnums=1))(
            t_eval, inputs_pred
        )
        flat_sse_grad, _ = tree_flatten(sse_grad)
        flat_sse_grad = np.array([f for f in flat_sse_grad]).flatten()
        (
            np.testing.assert_allclose(sse_val, flat_check_val, 1e3),
            f"Got: {sse_val}\nExpected: {flat_check_val}",
        )
        (
            np.testing.assert_allclose(flat_sse_grad, flat_check_grad, 1e3),
            f"Got: {sse_grad}\nExpected: {sse_grad}",
        )
