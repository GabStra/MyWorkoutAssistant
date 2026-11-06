package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.RunningSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.UUID

class SetNoteRoundTripTest {

    private val gson = GsonBuilder().registerTypeAdapter(
        com.gabstra.myworkoutassistant.shared.sets.Set::class.java, SetAdapter()
    ).create()

    @Test
    fun `note round-trips through every set type`() {
        val id = UUID.randomUUID()
        val sets = listOf(
            WeightSet(id, 8, 100.0, note = "3 reps @ RPE 8"),
            BodyWeightSet(id, 12, 0.0, note = "slow eccentric"),
            TimedDurationSet(id, 30_000, autoStart = true, autoStop = true, note = "hold the top"),
            EnduranceSet(id, 0, autoStart = true, autoStop = false, targetDistanceMeters = 15.0, note = "150 kg"),
            RunningSet(id, note = "400 m, easy pace"),
            com.gabstra.myworkoutassistant.shared.sets.WeightedEffortSet(id, targetDistanceMeters = 15.0, targetWeight = 150.0, note = "15 m @ 150 kg"),
            RestSet(id, 60, note = "shake out the arms"),
        )
        for (set in sets) {
            val roundTripped = gson.fromJson(gson.toJson(set, com.gabstra.myworkoutassistant.shared.sets.Set::class.java), com.gabstra.myworkoutassistant.shared.sets.Set::class.java)
            assertEquals(set.note, roundTripped.note)
            assertEquals(set, roundTripped)
        }
    }

    @Test
    fun `absent note stays null after round-trip`() {
        val set = WeightSet(UUID.randomUUID(), 5, 60.0)
        val roundTripped = gson.fromJson(gson.toJson(set, com.gabstra.myworkoutassistant.shared.sets.Set::class.java), com.gabstra.myworkoutassistant.shared.sets.Set::class.java)
        assertNull(roundTripped.note)
        assertEquals(set, roundTripped)
    }
}
