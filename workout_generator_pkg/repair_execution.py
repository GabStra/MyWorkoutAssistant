"""Shared solver and contract boundary for coordinated repair candidates."""

import copy


def solve_repair_candidate(workouts, requirements, equipment, restriction_policy, *,
                           repair_contract, requirements_id, allow_educated_load_guesses,
                           training_history, messages, preserve_source_selection,
                           redistribution_constraints, balance=False):
    from .joint_planning import solve_prescribed_week
    from .repair_contract import RepairContractError, carry_repair_contract, repair_contract_errors

    joint = solve_prescribed_week(workouts, requirements, equipment, restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        training_history=training_history, messages=messages, balance=balance,
        preserve_source_selection=preserve_source_selection,
        redistribution_constraints=redistribution_constraints)
    carried_contract = copy.deepcopy(repair_contract)
    carry_error = None
    contract_errors = []
    if joint.get('feasible') and carried_contract:
        try:
            carried_contract = carry_repair_contract(carried_contract, {}, {'workouts': workouts},
                {'workouts': joint['sessions']}, requirements_id=requirements_id)
        except RepairContractError as error:
            carry_error = error
        else:
            contract_errors = repair_contract_errors(carried_contract, {'workouts': joint['sessions']})
    return joint, carried_contract, carry_error, contract_errors
