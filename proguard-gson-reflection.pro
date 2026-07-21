# Concrete DTOs instantiated reflectively by Gson without a custom adapter.
# Keeping these classes prevents R8 class merging from replacing them with an
# abstract residual type while leaving the rest of the shared module optimizable.
-keep class com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup { *; }
-keep class com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef { *; }
-keep class com.gabstra.myworkoutassistant.shared.AppBackupArchive { *; }
-keep class com.gabstra.myworkoutassistant.shared.AppBackupDelta { *; }
-keep class com.gabstra.myworkoutassistant.shared.BackupListDelta { *; }
-keep class com.gabstra.myworkoutassistant.shared.WeeklyProgressOverride { *; }
-keep class com.gabstra.myworkoutassistant.shared.utils.SimpleSet { *; }
-keep class com.gabstra.myworkoutassistant.shared.workout.recovery.WorkoutRecoveryRuntimeSnapshot { *; }
-keep class com.gabstra.myworkoutassistant.shared.workout.recovery.SequenceItemDto { *; }
-keep class com.gabstra.myworkoutassistant.shared.workout.recovery.ContainerDto { *; }
-keep class com.gabstra.myworkoutassistant.shared.workout.recovery.ExerciseChildItemDto { *; }
-keep class com.gabstra.myworkoutassistant.shared.workout.recovery.StateDto { *; }
