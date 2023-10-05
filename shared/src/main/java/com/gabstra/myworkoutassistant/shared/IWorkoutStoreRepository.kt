package com.gabstra.myworkoutassistant.shared

interface IWorkoutStoreRepository {
    fun getWorkoutStore(): WorkoutStore
    fun saveWorkoutStore(workout: WorkoutStore)
}