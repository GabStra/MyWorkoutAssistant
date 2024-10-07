package com.gabstra.myworkoutassistant

import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BADMINTON
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BASEBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BASKETBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BIKING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BIKING_STATIONARY
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BOOT_CAMP
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_BOXING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_CALISTHENICS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_CRICKET
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_DANCING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ELLIPTICAL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_EXERCISE_CLASS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_FENCING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_FOOTBALL_AMERICAN
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_FOOTBALL_AUSTRALIAN
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_FRISBEE_DISC
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_GOLF
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_GUIDED_BREATHING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_GYMNASTICS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_HANDBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_HIKING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ICE_HOCKEY
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ICE_SKATING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_MARTIAL_ARTS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_OTHER_WORKOUT
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_PADDLING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_PARAGLIDING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_PILATES
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_RACQUETBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ROCK_CLIMBING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ROLLER_HOCKEY
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ROWING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_ROWING_MACHINE
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_RUGBY
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_RUNNING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_RUNNING_TREADMILL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SAILING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SCUBA_DIVING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SKATING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SKIING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SNOWBOARDING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SNOWSHOEING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SOCCER
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SOFTBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SQUASH
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_STAIR_CLIMBING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_STAIR_CLIMBING_MACHINE
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_STRENGTH_TRAINING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_STRETCHING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SURFING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SWIMMING_OPEN_WATER
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_SWIMMING_POOL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_TABLE_TENNIS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_TENNIS
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_VOLLEYBALL
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_WALKING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_WATER_POLO
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_WEIGHTLIFTING
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_WHEELCHAIR
import androidx.health.connect.client.records.ExerciseSessionRecord.Companion.EXERCISE_TYPE_YOGA
import java.util.Locale

class WorkoutTypes {
    companion object{
        val WORKOUT_TYPE_STRING_TO_INT_MAP: Map<String, Int> =
            mapOf(
                "badminton" to EXERCISE_TYPE_BADMINTON,
                "baseball" to EXERCISE_TYPE_BASEBALL,
                "basketball" to EXERCISE_TYPE_BASKETBALL,
                "biking" to EXERCISE_TYPE_BIKING,
                "biking_stationary" to EXERCISE_TYPE_BIKING_STATIONARY,
                "boxing" to EXERCISE_TYPE_BOXING,
                "cricket" to EXERCISE_TYPE_CRICKET,
                "dancing" to EXERCISE_TYPE_DANCING,
                "elliptical" to EXERCISE_TYPE_ELLIPTICAL,
                "exercise_class" to EXERCISE_TYPE_EXERCISE_CLASS,
                "fencing" to EXERCISE_TYPE_FENCING,
                "football_american" to EXERCISE_TYPE_FOOTBALL_AMERICAN,
                "football_australian" to EXERCISE_TYPE_FOOTBALL_AUSTRALIAN,
                "forward_twist" to EXERCISE_TYPE_CALISTHENICS,
                "frisbee_disc" to EXERCISE_TYPE_FRISBEE_DISC,
                "golf" to EXERCISE_TYPE_GOLF,
                "gymnastics" to EXERCISE_TYPE_GYMNASTICS,
                "handball" to EXERCISE_TYPE_HANDBALL,
                "hiking" to EXERCISE_TYPE_HIKING,
                "ice_hockey" to EXERCISE_TYPE_ICE_HOCKEY,
                "ice_skating" to EXERCISE_TYPE_ICE_SKATING,
                "jump_rope" to EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING,
                "martial_arts" to EXERCISE_TYPE_MARTIAL_ARTS,
                "pilates" to EXERCISE_TYPE_PILATES,
                "racquetball" to EXERCISE_TYPE_RACQUETBALL,
                "rock_climbing" to EXERCISE_TYPE_ROCK_CLIMBING,
                "roller_hockey" to EXERCISE_TYPE_ROLLER_HOCKEY,
                "rowing" to EXERCISE_TYPE_ROWING,
                "rowing_machine" to EXERCISE_TYPE_ROWING_MACHINE,
                "rugby" to EXERCISE_TYPE_RUGBY,
                "running" to EXERCISE_TYPE_RUNNING,
                "running_treadmill" to EXERCISE_TYPE_RUNNING_TREADMILL,
                "skiing" to EXERCISE_TYPE_SKIING,
                "snowboarding" to EXERCISE_TYPE_SNOWBOARDING,
                "soccer" to EXERCISE_TYPE_SOCCER,
                "stair_climbing" to EXERCISE_TYPE_STAIR_CLIMBING,
                "stair_climbing_machine" to EXERCISE_TYPE_STAIR_CLIMBING_MACHINE,
                "stretching" to EXERCISE_TYPE_STRETCHING,
                "surfing" to EXERCISE_TYPE_SURFING,
                "swimming_open_water" to EXERCISE_TYPE_SWIMMING_OPEN_WATER,
                "swimming_pool" to EXERCISE_TYPE_SWIMMING_POOL,
                "table_tennis" to EXERCISE_TYPE_TABLE_TENNIS,
                "tennis" to EXERCISE_TYPE_TENNIS,
                "volleyball" to EXERCISE_TYPE_VOLLEYBALL,
                "walking" to EXERCISE_TYPE_WALKING,
                "water_polo" to EXERCISE_TYPE_WATER_POLO,
                "weightlifting" to EXERCISE_TYPE_WEIGHTLIFTING,
                "wheelchair" to EXERCISE_TYPE_WHEELCHAIR,
                "workout" to EXERCISE_TYPE_OTHER_WORKOUT,
                "yoga" to EXERCISE_TYPE_YOGA,
                // These should always be at the end so reverse mapping are correct.
                "calisthenics" to EXERCISE_TYPE_CALISTHENICS,
                "high_intensity_interval_training" to
                        EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING,
                "strength_training" to EXERCISE_TYPE_STRENGTH_TRAINING,
            )

        val WORKOUT_TYPE_INT_TO_STRING_MAP =
            WORKOUT_TYPE_STRING_TO_INT_MAP.entries.associateBy({ it.value }, { it.key })

        fun GetNameFromInt(exerciseType: Int): String {
            if(!WORKOUT_TYPE_INT_TO_STRING_MAP.containsKey(exerciseType)){
                throw IllegalArgumentException("Invalid exercise type: $exerciseType")
            }

            return WORKOUT_TYPE_INT_TO_STRING_MAP[exerciseType]!!.replace('_', ' ').capitalize(Locale.ROOT)
        }
    }
}