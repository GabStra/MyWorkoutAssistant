"""Continuous, coupled body trajectories for rigid foot contacts."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize, least_squares, NonlinearConstraint, Bounds, BFGS
from scipy.sparse import csr_matrix, block_diag, kron, eye

from .contact_constraints import InfeasibleContactCorrection


class ContactTrajectory:
    def __init__(self, root, prepared, reach_constraints, fps, source_bounds):
        from . import foot_kinematics as geometry

        self.geometry = geometry
        self.count = len(root)
        self.prepared = prepared
        self.source_bounds = source_bounds
        self.fps = fps
        self.all_reach = reach_constraints
        self.reach = [(np.asarray(i), np.asarray(o), r) for i, o, r in reach_constraints if r > 0]
        self.angle_columns = {}
        self.knee_bounds = {}
        self.scale = max(leg[7] + leg[8] for leg in prepared.values())
        initial = list(root.ravel())
        self.bounds = [(None, None)] * len(initial)
        for indexes, offsets, radius in reach_constraints:
            if radius == 0:
                for index, offset in zip(indexes, offsets):
                    for axis in range(3):
                        self.bounds[index * 3 + axis] = (float(offset[axis]), float(offset[axis]))
                        initial[index * 3 + axis] = float(offset[axis])
        for side, leg in prepared.items():
            self.knee_bounds[side] = geometry._contact_knee_bounds(leg[1], leg[2], leg[3], source_bounds.get(side))
            indexes = np.flatnonzero(leg[14] | leg[15])
            columns = np.full(self.count, -1, dtype=int)
            columns[indexes] = np.arange(len(initial), len(initial) + len(indexes))
            self.angle_columns[side] = columns
            initial.extend(np.clip(leg[6][indexes], 1e-6, np.pi - 1e-6))
            self.bounds.extend([(1e-6, np.pi - 1e-6)] * len(indexes))
        self.initial = np.asarray(initial)
        second_difference = np.diff(np.eye(self.count), n=2, axis=0)
        self.system = np.eye(self.count) + (max(fps, 1.) * .10) ** 4 * second_difference.T @ second_difference
        _, self.constraint_frames = self.constraints(self.initial, with_frames=True)

    def objective(self, values):
        root = values[:self.count * 3].reshape(self.count, 3)
        return float(np.sum(root * (self.system @ root)) / self.scale**2)

    def gradient(self, values):
        gradient = np.zeros_like(values)
        root = values[:self.count * 3].reshape(self.count, 3)
        gradient[:self.count * 3] = (2 * self.system @ root / self.scale**2).ravel()
        return gradient

    def constraints(self, values, *, with_frames=False):
        f = self.geometry
        root = values[:self.count * 3].reshape(self.count, 3)
        margins, owners = [], []

        def add(indexes, value):
            margins.append(np.asarray(value).ravel())
            owners.append(indexes)

        for indexes, offsets, radius in self.reach:
            add(indexes, (radius**2 - np.sum((root[indexes] - offsets)**2, axis=1)) / self.scale**2)
        for side, leg in self.prepared.items():
            (_, hips, knees, ankles, targets, headings, _, thigh, shin, foot,
             _, _, _, full, heel, toe, lift) = leg
            low, high = self.knee_bounds[side]
            indexes = np.flatnonzero(full)
            if len(indexes):
                delta = targets[indexes] - headings[indexes] * foot - hips[indexes] - root[indexes]
                distance_squared = np.sum(delta**2, axis=1)
                add(indexes, (distance_squared - (thigh**2 + shin**2 - 2 * thigh * shin * np.cos(low[indexes]))) / self.scale**2)
                add(indexes, ((thigh**2 + shin**2 - 2 * thigh * shin * np.cos(high[indexes])) - distance_squared) / self.scale**2)
            indexes = np.flatnonzero(heel | toe)
            if not len(indexes):
                continue
            angles = values[self.angle_columns[side][indexes]]
            signed_foot = np.where(heel[indexes], -f.HEEL_BEHIND_ANKLE_RATIO * foot, foot)
            moved_hips = hips[indexes] + root[indexes]
            poles = f._source_knee_poles(hips[indexes], knees[indexes], ankles[indexes])
            candidate_knees, candidate_ankles, _, _ = f._leg_candidates(
                moved_hips, targets[indexes], headings[indexes], angles, np.ones(len(indexes)),
                thigh, shin, signed_foot, knee_poles=poles,
                source_axes=ankles[indexes] - hips[indexes])
            distance = np.linalg.norm(targets[indexes] - moved_hips, axis=1)
            effective = np.sqrt(shin**2 + signed_foot**2 - 2 * shin * signed_foot * np.cos(angles))
            add(indexes, (distance - np.abs(thigh - effective)) / self.scale)
            add(indexes, (thigh + effective - distance) / self.scale)
            knee_angles = f._knee_angles(moved_hips, candidate_knees, candidate_ankles)
            add(indexes, knee_angles - low[indexes])
            add(indexes, high[indexes] - knee_angles)
            toes = candidate_ankles + (targets[indexes] - candidate_ankles) * (foot / signed_foot)[:, None]
            clearance = np.where(heel[indexes],
                (toes[:, 1] - targets[indexes, 1]) / (1 + f.HEEL_BEHIND_ANKLE_RATIO),
                candidate_ankles[:, 1] - targets[indexes, 1])
            add(indexes, clearance / foot - lift[indexes])
            axis = f._unit(candidate_ankles - moved_hips)
            bend = candidate_knees - moved_hips
            bend -= axis * np.sum(bend * axis, axis=1, keepdims=True)
            transported_poles = f._transport_knee_poles(
                poles, ankles[indexes] - hips[indexes], targets[indexes] - moved_hips)
            add(indexes, np.sum(bend * transported_poles, axis=1) / self.scale)
        result = np.concatenate(margins) if margins else np.ones(1)
        if with_frames:
            return result, np.concatenate(owners) if owners else np.zeros(1, dtype=int)
        return result

    def jacobian(self, values):
        if not any(np.any(columns >= 0) for columns in self.angle_columns.values()):
            root = values[:self.count * 3].reshape(self.count, 3)
            gradients = []
            for indexes, offsets, radius in self.reach:
                gradients.append(-2 * (root[indexes] - offsets) / self.scale**2)
            for leg in self.prepared.values():
                indexes = np.flatnonzero(leg[13])
                if len(indexes):
                    delta = root[indexes] + leg[1][indexes] - leg[4][indexes] + leg[5][indexes] * leg[9]
                    gradients.extend([2 * delta / self.scale**2, -2 * delta / self.scale**2])
            result = np.zeros((len(self.constraint_frames), len(values)))
            if gradients:
                derivatives = np.concatenate(gradients)
                rows = np.arange(len(derivatives))
                for axis in range(3):
                    result[rows, self.constraint_frames * 3 + axis] = derivatives[:, axis]
            return result
        # Each constraint depends on one frame. Perturb all frames together
        # for each coordinate, then scatter to their columns: five vectorized
        # evaluations instead of hundreds of separate finite differences.
        baseline = self.constraints(values)
        result = np.zeros((len(baseline), len(values)))
        rows = np.arange(len(baseline))
        step = 1e-7
        for axis in range(3):
            changed = values.copy()
            changed[axis:self.count * 3:3] += step
            result[rows, self.constraint_frames * 3 + axis] = (self.constraints(changed) - baseline) / step
        for columns in self.angle_columns.values():
            active = columns >= 0
            changed = values.copy()
            changed[columns[active]] += step
            derivative = (self.constraints(changed) - baseline) / step
            matching = columns[self.constraint_frames] >= 0
            result[rows[matching], columns[self.constraint_frames[matching]]] = derivative[matching]
        return result

    def solve(self):
        initial = self.initial.copy()
        # Find an interior geometric seed before a constrained objective solve.
        # Grid samples initialize continuous variables; they never restrict
        # the feasible poses or replace the continuous solution.
        for columns in self.angle_columns.values():
            active = columns >= 0
            if not np.any(active):
                continue
            best = np.full(self.count, np.inf)
            chosen = initial[columns[active]].copy()
            for angle in self.geometry.ankle_proposal_angles()[1:-1]:
                trial = initial.copy()
                trial[columns[active]] = angle
                scores = np.bincount(self.constraint_frames,
                    weights=np.minimum(self.constraints(trial), 0.)**2, minlength=self.count)
                better = scores[active] < best[active]
                chosen[better] = angle
                best = np.minimum(best, scores)
            initial[columns[active]] = chosen
        local_models = [self.local_model(index) for index in range(self.count)]
        for model, columns in local_models:
            values = initial[columns]
            if model.constraints(values).min() >= -1e-8:
                continue
            free = np.array([low != high or low is None for low, high in model.bounds])
            if not np.any(free):
                # A separate support may fix the entire body here. Leave an
                # incompatible frame for the final feasibility report.
                continue
            lower = np.array([-np.inf if low is None else low for low, _ in model.bounds])
            upper = np.array([np.inf if high is None else high for _, high in model.bounds])

            def expand(x):
                expanded = values.copy()
                expanded[free] = x
                return expanded

            fit = least_squares(lambda x: np.minimum(model.constraints(expand(x)), 0.), values[free],
                bounds=(lower[free], upper[free]), max_nfev=160, ftol=1e-12, xtol=1e-12, gtol=1e-12)
            initial[columns] = expand(fit.x)
        if self.objective(initial) <= 1e-16 and self.constraints(initial).min() >= -1e-8:
            return self.solution(initial)
        # Optimize all frames together. Independent projections can choose
        # different feasible branches on adjacent frames and recreate a kink.
        hessian = block_diag([
            kron(csr_matrix(2 * self.system / self.scale**2), eye(3)),
            csr_matrix((len(initial) - self.count * 3,) * 2),
        ]).tocsr()
        lower = np.array([-np.inf if low is None else low for low, _ in self.bounds])
        upper = np.array([np.inf if high is None else high for _, high in self.bounds])
        best = initial.copy() if self.constraints(initial).min() >= -1e-8 else None

        def keep_feasible(values, state=None):
            nonlocal best
            if self.constraints(values).min() >= -1e-8 and (best is None or self.objective(values) < self.objective(best)):
                best = values.copy()

        result = minimize(self.objective, initial, jac=self.gradient, hess=lambda x: hessian,
            method="trust-constr", bounds=Bounds(lower, upper),
            constraints=NonlinearConstraint(self.constraints, 0., np.inf,
                jac=lambda x: csr_matrix(self.jacobian(x)), hess=BFGS()),
            callback=keep_feasible, options={"maxiter": 160, "gtol": 1e-8})
        keep_feasible(result.x)
        initial = best if best is not None else result.x
        margin = self.constraints(initial)
        if margin.min() < -1e-7:
            worst = int(np.argmin(margin))
            raise InfeasibleContactCorrection(
                f"Continuous support trajectory unresolved at frame {self.constraint_frames[worst]}; "
                f"minimum margin={margin[worst]:.6g}")
        return self.solution(initial)

    def solution(self, values):
        angles = {}
        for side, columns in self.angle_columns.items():
            track = np.full(self.count, np.pi / 2)
            active = columns >= 0
            track[active] = values[columns[active]]
            angles[side] = track
        return values[:self.count * 3].reshape(self.count, 3), angles

    def local_model(self, index):
        prepared = {}
        for side, leg in self.prepared.items():
            prepared[side] = tuple(value[index:index + 1] if field in {1,2,3,4,5,6,10,11,13,14,15,16}
                                   else value for field, value in enumerate(leg))
        reach = []
        for indexes, offsets, radius in self.all_reach:
            selected = np.flatnonzero(indexes == index)
            if len(selected):
                reach.append((np.zeros(len(selected), dtype=int), offsets[selected], radius))
        source_bounds = {side: bounds[index:index + 1] for side, bounds in self.source_bounds.items()}
        model = ContactTrajectory(self.initial[index * 3:index * 3 + 3].reshape(1, 3), prepared, reach,
                                  self.fps, source_bounds)
        columns = list(range(index * 3, index * 3 + 3))
        columns.extend(int(track[index]) for track in self.angle_columns.values() if track[index] >= 0)
        return model, np.array(columns)
