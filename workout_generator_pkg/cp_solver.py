"""Exact finite prescription models on CP-SAT, including optional execution circuits."""

import math
import time
from fractions import Fraction
from functools import lru_cache

_AUXILIARY_KINDS = frozenset({'duration_balance_bound', 'duration_balance_excess',
    'volume_target_deviation', 'fixed_volume_target_deviation', 'time_budget_excess',
    'reviewed_dose_deviation', 'exercise_distribution_peak', 'role_concentration_peak',
    'role_concentration_profile_peak', 'demand_distribution_peak', 'demand_colocation_peak',
    'goal_target_miss', 'goal_tier_peak'})
_DERIVED_INTEGER_KINDS = frozenset({'coverage_balance_deviation', 'distribution_deviation',
    'distribution_peak', 'exercise_count_deviation', 'execution_exposure_peak',
    'redistribution_peak', 'development_exposure_deficit'})


@lru_cache(maxsize=8192, typed=True)
def _rational(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'Unsupported finite solver quantity: {value!r}')
    result = Fraction(value).limit_denominator(1_000_000)
    if float(result) != value:
        raise ValueError(f'Quantity has no exact supported rational representation: {value!r}')
    return result


class SolverSession:
    """Reuse one weekly model while its rows only gain objective/dose locks."""

    def __init__(self):
        self._model = None
        self._variables = []
        self._scales = []
        self._signature = None
        self._features = []
        self._base_lattice = 1
        self._lattice = None
        self._circuits = {}
        self._validated_candidate = None

    @property
    def auxiliary_lattice(self):
        """Denominator of continuous auxiliaries in the currently prepared CP model."""
        return self._lattice

    @staticmethod
    def _variable_signature(variables):
        return tuple((item['lower'], item['upper'], item.get('integer', True),
            (item.get('domainIdentity') or {}).get('kind'),
            tuple((item.get('domainIdentity') or {}).get(key)
                for key in ('workoutIndex', 'tail', 'head'))
                if (item.get('domainIdentity') or {}).get('kind') == 'execution_arc' else ())
            for item in variables)

    @staticmethod
    def _row_lattice(features, lattice=1):
        for _, lower, upper, intercept, coefficients in features:
            for value in (lower, upper, intercept):
                if math.isfinite(value):
                    lattice = math.lcm(lattice, _rational(value).denominator)
            for value in coefficients.values():
                if value:
                    lattice = math.lcm(lattice, _rational(value).denominator)
        return lattice

    def _append_features(self, features):
        for label, lower, upper, intercept, coefficients in features:
            terms = {index: _rational(value) / self._scales[index]
                for index, value in coefficients.items() if value}
            factor = math.lcm(*(value.denominator for value in terms.values()),
                _rational(intercept).denominator,
                *(_rational(value).denominator for value in (lower, upper) if math.isfinite(value)))
            expression = sum(int(value * factor) * self._variables[index] for index, value in terms.items())
            if math.isfinite(lower):
                self._model.add(expression >= int((_rational(lower) - _rational(intercept)) * factor))
            if math.isfinite(upper):
                self._model.add(expression <= int((_rational(upper) - _rational(intercept)) * factor))
            self._features.append((label, lower, upper, intercept, dict(coefficients)))

    def _prepare(self, variables, features, cp_model):
        signature = self._variable_signature(variables)
        prefix = (self._model is not None and signature == self._signature
            and len(features) >= len(self._features)
            and all(before == after for before, after in zip(self._features, features)))
        base_lattice = self._base_lattice if prefix else math.lcm(*(
            _rational(value).denominator for item in variables
            for value in (item['lower'], item['upper'])))
        base_lattice = self._row_lattice(features[len(self._features):] if prefix else features, base_lattice)
        objective_values = [_rational(item.get('objectiveCost', 0)) for item in variables]
        lattice = math.lcm(base_lattice, *(value.denominator for value in objective_values))
        if lattice > 1_000_000:
            raise ValueError(f'Exact auxiliary lattice exceeds supported denominator: {lattice}')
        reuse = prefix and lattice == self._lattice
        appended = len(features) - len(self._features) if reuse else len(features)
        if not reuse:
            self._model = cp_model.CpModel()
            self._scales = [1 if item.get('integer', True) else lattice for item in variables]
            self._variables = [self._model.new_int_var(math.ceil(_rational(item['lower']) * scale),
                math.floor(_rational(item['upper']) * scale), str(index))
                for index, (item, scale) in enumerate(zip(variables, self._scales))]
            self._circuits = {}
            for index, item in enumerate(variables):
                identity = item.get('domainIdentity') or {}
                if identity.get('kind') == 'execution_arc':
                    self._circuits.setdefault(identity['workoutIndex'], []).append(
                        (identity['tail'], identity['head'], self._variables[index]))
            for arcs in self._circuits.values():
                self._model.add_circuit(arcs)
            self._features = []
            self._validated_candidate = None
        self._append_features(features[len(self._features):])
        self._signature, self._base_lattice, self._lattice = signature, base_lattice, lattice
        objective = [value / scale for value, scale in zip(objective_values, self._scales)]
        objective_scale = math.lcm(*(value.denominator for value in objective))
        self._model.minimize(sum(int(value * objective_scale) * variable
            for value, variable in zip(objective, self._variables)))
        self._model.clear_hints()
        return objective_scale, reuse, appended

    def _validate_candidate(self, candidate, variables, features, exact=None):
        if len(candidate) != len(variables):
            return False
        exact = exact if exact is not None else [_rational(value) for value in candidate]
        for value, variable, scale in zip(exact, variables, self._scales):
            if not _rational(variable['lower']) <= value <= _rational(variable['upper']):
                return False
            if (value * scale).denominator != 1:
                return False
        for _, lower, upper, intercept, coefficients in features:
            activity = _rational(intercept) + sum(_rational(value) * exact[index]
                for index, value in coefficients.items())
            if ((math.isfinite(lower) and activity < _rational(lower))
                    or (math.isfinite(upper) and activity > _rational(upper))):
                return False
        return True

    def _candidate(self, solver):
        return [solver.value(variable) / scale if scale != 1 else solver.value(variable)
            for variable, scale in zip(self._variables, self._scales)]

    def solve(self, variables, features, timeout_seconds=60, preserve_current=False,
              diagnostics=None, incumbent=None):
        """Solve supported finite epigraph models; preparation consumes the stage budget."""
        started = time.perf_counter()
        diagnostics = diagnostics if diagnostics is not None else {}
        try:
            from ortools.sat.python import cp_model
        except ImportError as error:
            diagnostics.update(backend='ortools_cp_sat', returnReason=str(error))
            return 'unavailable', None
        try:
            for variable in variables:
                if not variable.get('integer', True) and (variable.get('domainIdentity') or {}).get('kind') not in _AUXILIARY_KINDS:
                    raise ValueError(f'Unsupported continuous decision variable: {variable.get("domainIdentity")!r}')
            objective_scale, reused, appended = self._prepare(variables, features, cp_model)
            hints = incumbent.items() if isinstance(incumbent, dict) else enumerate(incumbent or [])
            for index, value in hints:
                if type(index) is not int or not 0 <= index < len(self._variables):
                    raise ValueError(f'Invalid incumbent variable index: {index!r}')
                hint = _rational(value) * self._scales[index]
                if hint.denominator == 1:
                    self._model.add_hint(self._variables[index], int(hint))
            validation = self._model.validate()
            if validation:
                raise ValueError(validation)
        except (ValueError, OverflowError, TypeError, IndexError) as error:
            self._model = None
            diagnostics.update(backend='ortools_cp_sat', returnReason='unsupported_exact_model',
                terminationMessage=str(error), modelBuildSeconds=time.perf_counter() - started)
            return 'unavailable', None
        build_seconds = time.perf_counter() - started
        remaining = max(0, timeout_seconds - build_seconds)
        diagnostics.update(backend='ortools_cp_sat', exactAuxiliaryLattice=self._lattice,
            modelBuildSeconds=build_seconds, modelReused=reused, appendedLinearConstraintCount=appended,
            executionCircuitCount=len(self._circuits), variableCount=len(variables),
            linearConstraintCount=len(features), executionArcCount=sum(map(len, self._circuits.values())),
            requestedBudgetSeconds=timeout_seconds, searchBudgetSeconds=remaining)
        fallback = None
        fallback_source = None
        fallback_exact = None
        if (not isinstance(incumbent, dict) and incumbent is not None
                and self._validated_candidate is not None
                and len(incumbent) == len(variables)
                and all(value == previous or
                    (variable.get('domainIdentity') or {}).get('kind') in
                        (_AUXILIARY_KINDS | _DERIVED_INTEGER_KINDS)
                    for value, previous, variable in zip(incumbent, self._validated_candidate, variables))
                and self._validate_candidate(incumbent, variables, features)):
            fallback = list(incumbent)
            fallback_source = 'validated_session_incumbent'
            fallback_exact = [_rational(value) for value in incumbent]

        if remaining <= 0:
            diagnostics.update(terminationStatus='UNKNOWN', incumbentFound=fallback is not None,
                incumbentValidated=fallback is not None, solveSeconds=0,
                returnReason='model_build_budget_exhausted',
                **({'incumbentSource': fallback_source} if fallback is not None else {}))
            return ('feasible', fallback) if fallback is not None else ('unproven', None)

        def new_solver(budget):
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = budget
            solver.parameters.num_search_workers = 8
            solver.parameters.random_seed = 0
            return solver

        solve_started = time.perf_counter()
        if isinstance(incumbent, dict) and incumbent:
            completion = new_solver(min(5, remaining / 2))
            completion.parameters.fix_variables_to_their_hinted_value = True
            completion.parameters.stop_after_first_solution = True
            completion_started = time.perf_counter()
            completion_status = completion.solve(self._model)
            diagnostics.update(hintCompletionBudgetSeconds=min(5, remaining / 2),
                hintCompletionSeconds=time.perf_counter() - completion_started,
                hintCompletionStatus=completion.status_name(completion_status))
            if completion_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                fallback = self._candidate(completion)
                exact = [Fraction(completion.value(variable), scale)
                    for variable, scale in zip(self._variables, self._scales)]
                if not self._validate_candidate(fallback, variables, features, exact):
                    raise RuntimeError('CP-SAT hint completion violates an exact source row or domain.')
                fallback_source = 'cp_verified_hint_completion'
                fallback_exact = exact
                self._model.clear_hints()
                for variable, value, scale in zip(self._variables, exact, self._scales):
                    self._model.add_hint(variable, int(value * scale))
        if fallback_exact is not None:
            costs = [_rational(variable.get('objectiveCost', 0)) for variable in variables]
            objective_value = sum(cost * value for cost, value in zip(costs, fallback_exact))
            domain_bound = sum(cost * _rational(variable['lower'] if cost >= 0 else variable['upper'])
                for cost, variable in zip(costs, variables))
            if objective_value == domain_bound:
                self._validated_candidate = list(fallback)
                diagnostics.update(terminationStatus='OPTIMAL', incumbentFound=True, incumbentValidated=True,
                    incumbentSource=fallback_source, objectiveBound=float(domain_bound),
                    objectiveValue=float(objective_value), searchBudgetSeconds=0,
                    boundWitness='verified_incumbent_matches_exact_variable_domain_lower_bound',
                    solveSeconds=time.perf_counter() - solve_started,
                    returnReason='optimal_variable_domain_bound_witness')
                return 'optimal', fallback
        remaining = max(0, timeout_seconds - (time.perf_counter() - started))
        diagnostics['searchBudgetSeconds'] = remaining
        if remaining > 0:
            solver = new_solver(remaining)
            status = solver.solve(self._model)
            candidate = (self._candidate(solver) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None)
            status_name = solver.status_name(status)
            objective_bound = solver.best_objective_bound / objective_scale
        else:
            status, candidate, status_name, objective_bound = cp_model.UNKNOWN, None, 'UNKNOWN', None
        if candidate is not None:
            exact = [Fraction(solver.value(variable), scale)
                for variable, scale in zip(self._variables, self._scales)]
            if not self._validate_candidate(candidate, variables, features, exact):
                raise RuntimeError('CP-SAT candidate violates an exact source row or variable domain.')
        elif fallback is not None and status == cp_model.UNKNOWN:
            candidate = fallback
        if candidate is not None:
            self._validated_candidate = list(candidate)
        diagnostics.update(terminationStatus=status_name,
            incumbentFound=candidate is not None, incumbentValidated=candidate is not None,
            objectiveBound=objective_bound, solveSeconds=time.perf_counter() - solve_started,
            returnReason=('feasible_incumbent_after_unknown' if candidate is fallback and fallback is not None
                else status_name.lower()),
            **({'incumbentSource': fallback_source} if candidate is fallback and fallback is not None else {}))
        result_status = ({cp_model.OPTIMAL: 'optimal', cp_model.FEASIBLE: 'feasible',
            cp_model.INFEASIBLE: 'infeasible', cp_model.MODEL_INVALID: 'unavailable'}
            .get(status, 'unproven'))
        return ('feasible' if candidate is not None and result_status == 'unproven' else result_status, candidate)


def solve(variables, features, timeout_seconds=60, preserve_current=False,
          diagnostics=None, incumbent=None, session=None):
    """Standalone calls are fresh; one weekly caller may supply an in-memory session."""
    return (session if session is not None else SolverSession()).solve(variables, features,
        timeout_seconds=timeout_seconds, preserve_current=preserve_current,
        diagnostics=diagnostics, incumbent=incumbent)
