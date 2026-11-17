package com.gabstra.myworkoutassistant.shared.workout.history

import android.content.Context
import androidx.room.withTransaction
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

/** Corrects only the calendar date of an imported history whose source did not provide a start time. */
object WorkoutHistoryDateCorrectionService {
    suspend fun correctImportedDate(
        context: Context,
        profileId: String,
        historyId: UUID,
        correctedDate: LocalDate,
    ): WorkoutHistory {
        val appContext = context.applicationContext
        val activeProfileId = Profiles.activeProfileId(appContext)
        require(profileId == activeProfileId) {
            "The history can only be corrected in its active profile."
        }
        val database = AppDatabase.getDatabase(appContext, profileId)
        return correctImportedDate(database, profileId, activeProfileId, historyId, correctedDate)
    }

    internal suspend fun correctImportedDate(
        database: AppDatabase,
        profileId: String,
        activeProfileId: String,
        historyId: UUID,
        correctedDate: LocalDate,
    ): WorkoutHistory {
        require(profileId == activeProfileId) {
            "The history can only be corrected in its active profile."
        }
        return database.withTransaction {
            val history = database.workoutHistoryDao().getWorkoutHistoryById(historyId)
                ?: throw IllegalArgumentException("The imported workout history no longer exists.")
            require(history.origin == WorkoutHistoryOrigin.USER_IMPORTED && !history.startTimeKnown) {
                "Only imported histories with an unknown start time can have their date corrected."
            }
            val updated = history.copy(
                date = correctedDate,
                time = LocalTime.MIDNIGHT,
                startTime = LocalDateTime.of(correctedDate, LocalTime.MIDNIGHT),
                startTimeKnown = false,
            )
            database.workoutHistoryDao().update(updated)
            updated
        }
    }
}
