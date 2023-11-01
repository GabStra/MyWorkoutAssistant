package com.gabstra.myworkoutassistant.shared

interface IWorkoutStoreRepository {
    fun getWorkoutStore(): WorkoutStore
    fun saveWorkoutStore(workoutStore: WorkoutStore)
    fun saveWorkoutStoreFromJson(workoutStoreJson : String)
}