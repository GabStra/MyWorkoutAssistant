package com.gabstra.myworkoutassistant.shared

const val UNASSIGNED_PLAN_NAME = "Unassigned"

/**
 * True when [name] is the legacy "Unassigned" plan name.
 *
 * The match is exact: the repository dissolves every stored plan with this name into ungrouped
 * workouts, so the name is reserved and can never be persisted as a real plan. Names that only
 * resemble it (for example "unassigned", "Unassigned ", or "Unassigned 2") remain ordinary plans.
 */
fun isReservedWorkoutPlanName(name: String): Boolean = name == UNASSIGNED_PLAN_NAME
