package com.gabstra.myworkoutassistant

import android.content.Intent
import com.gabstra.myworkoutassistant.data.OPEN_ACTIVE_WORKOUT_ACTION
import com.gabstra.myworkoutassistant.data.configureOpenActiveWorkoutIntent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class NotificationUtilsTest {

    @Test
    fun configureOpenActiveWorkoutIntent_setsExpectedActionFlagsAndWorkoutId() {
        val workoutId = UUID.randomUUID()

        val intent = Intent().configureOpenActiveWorkoutIntent(workoutId)

        assertEquals(OPEN_ACTIVE_WORKOUT_ACTION, intent.action)
        assertEquals(
            Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP,
            intent.flags
        )
        assertEquals(workoutId.toString(), intent.getStringExtra("WORKOUT_ID"))
    }

    @Test
    fun configureOpenActiveWorkoutIntent_clearsWorkoutIdWhenMissing() {
        val intent = Intent().apply {
            putExtra("WORKOUT_ID", UUID.randomUUID().toString())
        }.configureOpenActiveWorkoutIntent(null)

        assertFalse(intent.hasExtra("WORKOUT_ID"))
        assertTrue(intent.flags and Intent.FLAG_ACTIVITY_CLEAR_TOP != 0)
    }
}
