package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.running.defaultDistanceUnit

/**
 * Splits [WorkoutStore] into the part shared by every profile on this install and the part
 * that belongs to one person.
 *
 * Shared: exercise library, workouts, equipment, plans and weekly progress overrides.
 * Personal: body metrics, heart-rate values, progression, deload, distance unit, HR straps.
 */

fun WorkoutStore.sharedContentOnly(): WorkoutStore = copy(
    externalHeartRateConfigs = emptyList(),
    birthDateYear = 0,
    weightKg = 0.0,
    heightCm = null,
    progressionPercentageAmount = 0.0,
    measuredMaxHeartRate = null,
    restingHeartRate = null,
    sex = null,
    gender = null,
    estimatedVo2MaxMlKgMin = null,
    vo2MaxSource = null,
    vo2MaxEstimatedAtEpochDay = null,
    deloadConfig = DeloadConfig(),
    distanceUnit = defaultDistanceUnit(),
    visibleWorkoutPlanIds = null,
)

fun WorkoutStore.personalSettingsOnly(): WorkoutStore = copy(
    exerciseDefinitions = emptyList(),
    workouts = emptyList(),
    equipments = emptyList(),
    accessoryEquipments = emptyList(),
    workoutPlans = emptyList(),
    weeklyProgressOverrides = emptyList(),
)

fun WorkoutStore.mergedWithPersonalSettingsOf(personal: WorkoutStore): WorkoutStore = copy(
    externalHeartRateConfigs = personal.externalHeartRateConfigs,
    birthDateYear = personal.birthDateYear,
    weightKg = personal.weightKg,
    heightCm = personal.heightCm,
    progressionPercentageAmount = personal.progressionPercentageAmount,
    measuredMaxHeartRate = personal.measuredMaxHeartRate,
    restingHeartRate = personal.restingHeartRate,
    sex = personal.sex,
    gender = personal.gender,
    estimatedVo2MaxMlKgMin = personal.estimatedVo2MaxMlKgMin,
    vo2MaxSource = personal.vo2MaxSource,
    vo2MaxEstimatedAtEpochDay = personal.vo2MaxEstimatedAtEpochDay,
    deloadConfig = personal.deloadConfig,
    distanceUnit = personal.distanceUnit,
    visibleWorkoutPlanIds = personal.visibleWorkoutPlanIds,
)
